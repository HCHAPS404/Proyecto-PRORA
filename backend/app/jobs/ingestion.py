"""Process canonical, aggregated institutional CSV files in the background."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.ingestion.snapshots import RawFileSnapshotWriter, SnapshotArtifact
from app.ml.config import normalize_disease
from app.models.epidemiology import (
    ClimateObservation,
    DataSource,
    DeforestationObservation,
    EpidemiologicalObservation,
    IngestionRun,
    Municipality,
    PipelineStatus,
    SocioeconomicIndicator,
    SourceStatus,
    VaccinationCoverage,
)
from app.services.canonical_store import (
    CanonicalValidationError,
    add_quarantine,
    store_snapshot,
)

EXPECTED_COLUMNS: dict[str, set[str]] = {
    "epidemiology": {
        "municipality_code",
        "disease",
        "week_start",
        "cases",
        "population",
        "is_preliminary",
        "quality_score",
    },
    "climate": {
        "municipality_code",
        "week_start",
        "precipitation_mm",
        "temperature_mean_c",
        "humidity_relative_pct",
        "quality_score",
    },
    "vaccination": {
        "municipality_code",
        "year",
        "month",
        "vaccine",
        "target_population",
        "doses_applied",
        "coverage_pct",
    },
    "deforestation": {
        "municipality_code",
        "year",
        "quarter",
        "deforested_hectares",
        "early_warning_count",
        "has_active_warning",
    },
    "socioeconomic": {
        "municipality_code",
        "year",
        "water_access_pct",
        "sewer_access_pct",
        "overcrowding_pct",
        "nbi_pct",
    },
}

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "epidemiology": {"municipality_code", "disease", "week_start", "cases"},
    "climate": {"municipality_code", "week_start"},
    "vaccination": {"municipality_code", "year", "month", "vaccine", "coverage_pct"},
    "deforestation": {"municipality_code", "year", "quarter"},
    "socioeconomic": {"municipality_code", "year"},
}


async def claim_ingestion_job(session: AsyncSession) -> IngestionRun | None:
    run = await session.scalar(
        select(IngestionRun)
        .where(IngestionRun.status == PipelineStatus.PENDING.value)
        .order_by(IngestionRun.started_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    run.status = PipelineStatus.RUNNING.value
    run.started_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run)
    return run


async def process_ingestion_job(
    session: AsyncSession,
    run: IngestionRun,
    settings: Settings | None = None,
) -> None:
    runtime = settings or get_settings()
    run_id = run.id
    source_id = run.source_id
    if run.provenance.get("kind") == "official_source_sync":
        from app.services.source_sync import process_source_sync

        await process_source_sync(session, run, runtime)
        return
    source = await session.get(DataSource, source_id)
    try:
        dataset_type = str(run.provenance["dataset_type"])
        upload_path = str(run.provenance["upload_path"])
        actual_checksum, actual_size = await anyio.to_thread.run_sync(
            _file_integrity, upload_path
        )
        expected_size = int(run.provenance.get("content_bytes", actual_size))
        if actual_checksum != run.checksum or actual_size != expected_size:
            raise DomainError(
                "integrity_mismatch",
                "El archivo cambió entre la recepción y el procesamiento",
                409,
                {
                    "expected_sha256": run.checksum,
                    "actual_sha256": actual_checksum,
                    "expected_bytes": expected_size,
                    "actual_bytes": actual_size,
                },
            )
        frame = await anyio.to_thread.run_sync(_read_csv, upload_path)
        _validate_schema(frame, dataset_type)
        artifact = await anyio.to_thread.run_sync(
            _archive_institutional_csv,
            upload_path,
            runtime.raw_snapshot_dir,
            run.source_id,
            run.id,
            dataset_type,
            str(run.provenance.get("original_filename", "upload.csv")),
            len(frame),
            sorted(str(column) for column in frame.columns),
        )
        store_snapshot(session, run, artifact)
        run.provenance = {
            **dict(run.provenance or {}),
            "snapshot_sha256": artifact.sha256,
            "schema_sha256": artifact.schema_sha256,
        }
        run.rows_read = len(frame)
        known_codes = set(
            (
                await session.scalars(
                    select(Municipality.code).where(
                        Municipality.code.in_(_municipality_codes(frame))
                    )
                )
            ).all()
        )
        accepted = 0
        errors: list[dict[str, Any]] = []
        for row_number, record in enumerate(frame.to_dict(orient="records"), start=2):
            try:
                code = _municipality_code(record.get("municipality_code"))
                if code not in known_codes:
                    raise ValueError(f"DIVIPOLA desconocido: {code}")
                await _upsert_record(session, run, dataset_type, code, record)
                accepted += 1
            except (TypeError, ValueError, DomainError) as exc:
                await add_quarantine(
                    session,
                    run,
                    row_number,
                    record,
                    CanonicalValidationError("institutional_row_invalid", str(exc)),
                )
                if len(errors) < 25:
                    errors.append({"row": row_number, "reason": str(exc)[:300]})

        rejected = len(frame) - accepted
        run.rows_accepted = accepted
        run.rows_rejected = rejected
        run.quality_report = {
            "schema": dataset_type,
            "acceptance_rate": accepted / max(1, len(frame)),
            "quarantine_sample": errors,
            "patient_level_columns_allowed": False,
        }
        run.finished_at = datetime.now(UTC)
        if accepted == 0:
            run.status = PipelineStatus.FAILED.value
            run.error_message = "Ninguna fila superó los controles de calidad"
        elif rejected:
            run.status = PipelineStatus.PARTIAL.value
        else:
            run.status = PipelineStatus.SUCCEEDED.value
        if source is not None:
            source.last_checked_at = run.finished_at
            if accepted:
                source.last_success_at = run.finished_at
                source.status = SourceStatus.ACTIVE.value
        await session.commit()
        await anyio.to_thread.run_sync(_remove_upload, Path(upload_path))
    except Exception as exc:
        await session.rollback()
        persisted = await session.get(IngestionRun, run_id)
        persisted_source = await session.get(DataSource, source_id)
        if persisted is not None:
            persisted.status = PipelineStatus.FAILED.value
            persisted.finished_at = datetime.now(UTC)
            persisted.error_message = str(exc)[:4000]
            if persisted_source is not None:
                persisted_source.last_checked_at = persisted.finished_at
            await session.commit()


def _file_integrity(path_value: str) -> tuple[str, int]:
    from hashlib import sha256

    path = Path(path_value).expanduser().resolve()
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _archive_institutional_csv(
    path_value: str,
    snapshot_root: str,
    source_id: str,
    run_id: str,
    dataset_type: str,
    original_filename: str,
    row_count: int,
    columns: list[str],
) -> SnapshotArtifact:
    writer = RawFileSnapshotWriter(
        root=snapshot_root,
        source_id=source_id,
        run_id=run_id,
        source_url="institutional-upload://local",
        media_type="text/csv",
        filename="source.csv",
        query={"dataset_type": dataset_type},
        publication={"original_filename": Path(original_filename).name},
    )
    try:
        with Path(path_value).expanduser().resolve().open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                writer.append_chunk(chunk)
        return writer.finalize(
            row_count=row_count,
            schema_descriptor={
                "dataset_type": dataset_type,
                "columns": columns,
                "patient_level_columns_allowed": False,
            },
        )
    except Exception:
        writer.abort()
        raise


def _remove_upload(path: Path) -> None:
    path.unlink(missing_ok=True)


def _validate_schema(frame: pd.DataFrame, dataset_type: str) -> None:
    if dataset_type not in EXPECTED_COLUMNS:
        raise ValueError("Tipo de conjunto no soportado")
    columns = {str(column).strip() for column in frame.columns}
    missing = REQUIRED_COLUMNS[dataset_type] - columns
    unexpected = columns - EXPECTED_COLUMNS[dataset_type]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")
    if unexpected:
        raise ValueError(
            "El archivo contiene columnas no canónicas; se bloquea para evitar datos personales: "
            + ", ".join(sorted(unexpected))
        )
    if frame.empty:
        raise ValueError("El archivo no contiene registros")


def _read_csv(path_value: str) -> pd.DataFrame:
    path = Path(path_value).expanduser().resolve()
    return pd.read_csv(path, dtype={"municipality_code": "string"})


def _municipality_codes(frame: pd.DataFrame) -> list[str]:
    return sorted({_municipality_code(value) for value in frame["municipality_code"]})


def _municipality_code(value: Any) -> str:
    text = str(value).strip().removesuffix(".0").zfill(5)
    if len(text) != 5 or not text.isdigit():
        raise ValueError("municipality_code debe ser DIVIPOLA de 5 dígitos")
    return text


async def _upsert_record(
    session: AsyncSession,
    run: IngestionRun,
    dataset_type: str,
    code: str,
    record: dict[str, Any],
) -> None:
    if dataset_type == "epidemiology":
        await _upsert_epidemiology(session, run, code, record)
    elif dataset_type == "climate":
        await _upsert_climate(session, run, code, record)
    elif dataset_type == "vaccination":
        await _upsert_vaccination(session, run, code, record)
    elif dataset_type == "deforestation":
        await _upsert_deforestation(session, run, code, record)
    elif dataset_type == "socioeconomic":
        await _upsert_socioeconomic(session, run, code, record)


async def _upsert_epidemiology(
    session: AsyncSession, run: IngestionRun, code: str, record: dict[str, Any]
) -> None:
    disease = normalize_disease(str(record["disease"]))
    if disease not in {"dengue", "malaria", "chikunguna", "zika", "leishmaniasis", "ira"}:
        raise ValueError(f"Enfermedad no priorizada: {disease}")
    week = pd.Timestamp(record["week_start"]).date()
    cases = _required_int(record["cases"], minimum=0)
    population = _optional_int(record.get("population"), minimum=1)
    item = await session.scalar(
        select(EpidemiologicalObservation).where(
            EpidemiologicalObservation.municipality_code == code,
            EpidemiologicalObservation.disease == disease,
            EpidemiologicalObservation.week_start == week,
        )
    )
    values = {
        "epidemiological_week": int(week.isocalendar().week),
        "epidemiological_year": int(week.isocalendar().year),
        "cases": cases,
        "population": population,
        "incidence_per_100k": cases * 100_000 / population if population else None,
        "is_preliminary": _as_bool(record.get("is_preliminary"), True),
        "quality_score": _optional_float(record.get("quality_score"), 1.0, 0, 1),
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if item is None:
        session.add(
            EpidemiologicalObservation(
                municipality_code=code,
                disease=disease,
                week_start=week,
                **values,
            )
        )
    else:
        _assign(item, values)


async def _upsert_climate(
    session: AsyncSession, run: IngestionRun, code: str, record: dict[str, Any]
) -> None:
    week = pd.Timestamp(record["week_start"]).date()
    item = await session.scalar(
        select(ClimateObservation).where(
            ClimateObservation.municipality_code == code,
            ClimateObservation.week_start == week,
        )
    )
    values = {
        "precipitation_mm": _optional_float(record.get("precipitation_mm"), None, 0),
        "temperature_mean_c": _optional_float(record.get("temperature_mean_c")),
        "humidity_relative_pct": _optional_float(record.get("humidity_relative_pct"), None, 0, 100),
        "quality_score": _optional_float(record.get("quality_score"), 1.0, 0, 1),
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if item is None:
        session.add(ClimateObservation(municipality_code=code, week_start=week, **values))
    else:
        _assign(item, values)


async def _upsert_vaccination(
    session: AsyncSession, run: IngestionRun, code: str, record: dict[str, Any]
) -> None:
    year = _required_int(record["year"], 2000, 2100)
    month = _required_int(record["month"], 1, 12)
    vaccine = str(record["vaccine"]).strip()
    if not vaccine:
        raise ValueError("vaccine es obligatorio")
    item = await session.scalar(
        select(VaccinationCoverage).where(
            VaccinationCoverage.municipality_code == code,
            VaccinationCoverage.year == year,
            VaccinationCoverage.month == month,
            VaccinationCoverage.vaccine == vaccine,
        )
    )
    values = {
        "target_population": _optional_int(record.get("target_population"), minimum=0),
        "doses_applied": _optional_int(record.get("doses_applied"), minimum=0),
        "coverage_pct": _optional_float(record.get("coverage_pct"), None, 0, 150),
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if values["coverage_pct"] is None:
        raise ValueError("coverage_pct es obligatorio")
    if item is None:
        session.add(
            VaccinationCoverage(
                municipality_code=code, year=year, month=month, vaccine=vaccine, **values
            )
        )
    else:
        _assign(item, values)


async def _upsert_deforestation(
    session: AsyncSession, run: IngestionRun, code: str, record: dict[str, Any]
) -> None:
    year = _required_int(record["year"], 2000, 2100)
    quarter = _required_int(record["quarter"], 1, 4)
    item = await session.scalar(
        select(DeforestationObservation).where(
            DeforestationObservation.municipality_code == code,
            DeforestationObservation.year == year,
            DeforestationObservation.quarter == quarter,
        )
    )
    values = {
        "deforested_hectares": _optional_float(record.get("deforested_hectares"), None, 0),
        "early_warning_count": _optional_int(record.get("early_warning_count"), minimum=0),
        "has_active_warning": _as_bool(record.get("has_active_warning"), False),
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if item is None:
        session.add(
            DeforestationObservation(municipality_code=code, year=year, quarter=quarter, **values)
        )
    else:
        _assign(item, values)


async def _upsert_socioeconomic(
    session: AsyncSession, run: IngestionRun, code: str, record: dict[str, Any]
) -> None:
    year = _required_int(record["year"], 1900, 2100)
    item = await session.scalar(
        select(SocioeconomicIndicator).where(
            SocioeconomicIndicator.municipality_code == code,
            SocioeconomicIndicator.year == year,
        )
    )
    values = {
        "water_access_pct": _optional_float(record.get("water_access_pct"), None, 0, 100),
        "sewer_access_pct": _optional_float(record.get("sewer_access_pct"), None, 0, 100),
        "overcrowding_pct": _optional_float(record.get("overcrowding_pct"), None, 0, 100),
        "nbi_pct": _optional_float(record.get("nbi_pct"), None, 0, 100),
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if item is None:
        session.add(SocioeconomicIndicator(municipality_code=code, year=year, **values))
    else:
        _assign(item, values)


def _assign(item: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(item, key, value)


def _required_int(value: Any, minimum: int | None = None, maximum: int | None = None) -> int:
    if pd.isna(value):
        raise ValueError("Valor entero obligatorio ausente")
    number = int(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"Valor menor que {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"Valor mayor que {maximum}")
    return number


def _optional_int(value: Any, minimum: int | None = None) -> int | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return _required_int(value, minimum)


def _optional_float(
    value: Any,
    default: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return default
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"Valor menor que {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"Valor mayor que {maximum}")
    return number


def _as_bool(value: Any, default: bool) -> bool:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError("Valor booleano inválido")
