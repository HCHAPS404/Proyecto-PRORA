"""Build and persist the canonical municipal-week panel consumed by PRORA models."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import (
    ClimateObservation,
    DeforestationObservation,
    DepartmentVaccinationCoverage,
    EpidemiologicalObservation,
    Municipality,
    SocioeconomicIndicator,
    VaccinationCoverage,
)

DATASET_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    """An exact model input plus its immutable lineage metadata."""

    frame: pd.DataFrame
    fingerprint: str
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    uri: str
    sha256: str
    manifest_uri: str


async def build_training_panel(session: AsyncSession, disease: str) -> pd.DataFrame:
    """Backward-compatible convenience wrapper returning only the panel."""

    return (await build_training_dataset(session, disease)).frame


async def build_training_dataset(session: AsyncSession, disease: str) -> TrainingDataset:
    """Read a traceable database snapshot and produce one row per calendar week.

    Missing epidemiological reports remain ``NaN`` rather than becoming zero.
    Calendar rows are nevertheless materialized, so ``lag_1`` always means one
    real week and never merely "the previous record". Covariates are joined only
    to their effective period and forward-filled within a municipality; no
    future value is back-filled into the past.
    """

    observations = list(
        (
            await session.scalars(
                select(EpidemiologicalObservation)
                .where(EpidemiologicalObservation.disease == disease)
                .order_by(
                    EpidemiologicalObservation.municipality_code,
                    EpidemiologicalObservation.week_start,
                )
            )
        ).all()
    )
    if not observations:
        empty = pd.DataFrame(columns=["week", "disease", "territory_id", "cases"])
        fingerprint = frame_fingerprint(empty)
        return TrainingDataset(
            frame=empty,
            fingerprint=fingerprint,
            manifest=_dataset_manifest(empty, disease, [], fingerprint),
        )

    municipality_codes = sorted({item.municipality_code for item in observations})
    municipalities = {
        item.code: item
        for item in (
            await session.scalars(
                select(Municipality).where(Municipality.code.in_(municipality_codes))
            )
        ).all()
    }
    observed_frame = pd.DataFrame(
        [
            {
                "week": pd.Timestamp(item.week_start),
                "disease": item.disease,
                "territory_id": item.municipality_code,
                "cases": float(item.cases),
                "population": item.population,
                "case_quality": item.quality_score,
                "is_preliminary": float(item.is_preliminary),
                "case_reported": 1.0,
            }
            for item in observations
        ]
    )
    frame = _calendarize(observed_frame, disease)
    population_by_territory = {
        code: item.population
        for code, item in municipalities.items()
        if item.population is not None
    }
    frame["population"] = frame["population"].fillna(
        frame["territory_id"].map(population_by_territory)
    )
    frame["case_reported"] = frame["case_reported"].fillna(0.0)
    frame["department_code"] = frame["territory_id"].map(
        {code: item.department_code for code, item in municipalities.items()}
    )
    frame["week"] = pd.to_datetime(frame["week"])
    # pandas exposes calendar components as int32 on some runtimes while SQL
    # integer columns materialize as int64. ``merge_asof`` requires identical
    # key dtypes, so normalize the complete effective-period key contract here.
    frame["year"] = frame["week"].dt.year.astype("int64")
    frame["month"] = frame["week"].dt.month.astype("int64")
    frame["quarter"] = frame["week"].dt.quarter.astype("int64")
    minimum_week = frame["week"].min().date()
    maximum_week = frame["week"].max().date()

    climate = list(
        (
            await session.scalars(
                select(ClimateObservation).where(
                    ClimateObservation.municipality_code.in_(municipality_codes),
                    ClimateObservation.week_start >= minimum_week,
                    ClimateObservation.week_start <= maximum_week,
                )
            )
        ).all()
    )
    if climate:
        climate_frame = pd.DataFrame(
            [
                {
                    "territory_id": item.municipality_code,
                    "week": pd.Timestamp(item.week_start),
                    "precipitation": item.precipitation_mm,
                    "temperature": item.temperature_mean_c,
                    "humidity": item.humidity_relative_pct,
                    "climate_quality": item.quality_score,
                }
                for item in climate
            ]
        )
        frame = frame.merge(climate_frame, on=["territory_id", "week"], how="left")

    vaccination = list(
        (
            await session.scalars(
                select(DepartmentVaccinationCoverage).where(
                    DepartmentVaccinationCoverage.department_code.in_(
                        sorted(frame["department_code"].dropna().unique().tolist())
                    ),
                    DepartmentVaccinationCoverage.year <= int(frame["year"].max()),
                )
            )
        ).all()
    )
    if vaccination:
        vaccination_frame = pd.DataFrame(
            [
                {
                    "department_code": item.department_code,
                    "year": item.year,
                    "vaccine": item.vaccine,
                    "coverage": item.coverage_pct,
                }
                for item in vaccination
            ]
        )
        vaccination_frame = vaccination_frame.pivot_table(
            index=["department_code", "year"],
            columns="vaccine",
            values="coverage",
            aggfunc="mean",
        ).reset_index()
        coverage_columns = []
        renamed = {}
        for column in vaccination_frame.columns:
            if column in {"department_code", "year"}:
                continue
            normalized = "".join(
                character if character.isalnum() else "_" for character in str(column)
            )
            name = f"pai_program_coverage_{normalized.strip('_').lower()}"
            renamed[column] = name
            coverage_columns.append(name)
        vaccination_frame = vaccination_frame.rename(columns=renamed)
        vaccination_frame["pai_health_system_access_proxy"] = vaccination_frame[
            coverage_columns
        ].mean(axis=1, skipna=True)
        frame = frame.merge(
            vaccination_frame,
            on=["department_code", "year"],
            how="left",
        )
        frame["pai_proxy_territory_level"] = "department"

    municipal_vaccination = list(
        (
            await session.scalars(
                select(VaccinationCoverage).where(
                    VaccinationCoverage.municipality_code.in_(municipality_codes),
                    VaccinationCoverage.year <= int(frame["year"].max()),
                )
            )
        ).all()
    )
    if municipal_vaccination:
        # Published municipal PAI files are cumulative cut-offs. A cut-off for
        # month M is considered available on the first day of M+1, then joined
        # backward only. This avoids leaking an end-of-month value into weeks
        # that occurred before the cut-off was complete.
        municipal_frame = pd.DataFrame(
            [
                {
                    "territory_id": item.municipality_code,
                    "effective_week": pd.Timestamp(
                        year=item.year,
                        month=item.month,
                        day=1,
                    )
                    + pd.offsets.MonthBegin(1),
                    "vaccine": item.vaccine,
                    "coverage": item.coverage_pct,
                }
                for item in municipal_vaccination
            ]
        )
        municipal_frame = municipal_frame.pivot_table(
            index=["territory_id", "effective_week"],
            columns="vaccine",
            values="coverage",
            aggfunc="mean",
        ).reset_index()
        municipal_columns: list[str] = []
        renamed: dict[Any, str] = {}
        for column in municipal_frame.columns:
            if column in {"territory_id", "effective_week"}:
                continue
            normalized = "".join(
                character if character.isalnum() else "_" for character in str(column)
            )
            name = f"pai_municipal_coverage_{normalized.strip('_').lower()}"
            renamed[column] = name
            municipal_columns.append(name)
        municipal_frame = municipal_frame.rename(columns=renamed)
        pieces = []
        for territory, territory_frame in frame.groupby("territory_id", sort=True):
            coverage = municipal_frame[municipal_frame["territory_id"] == territory].drop(
                columns="territory_id"
            )
            if coverage.empty:
                pieces.append(territory_frame)
                continue
            pieces.append(
                pd.merge_asof(
                    territory_frame.sort_values("week"),
                    coverage.sort_values("effective_week"),
                    left_on="week",
                    right_on="effective_week",
                    direction="backward",
                ).drop(columns="effective_week")
            )
        frame = pd.concat(pieces, ignore_index=True)
        municipal_proxy = frame[municipal_columns].mean(axis=1, skipna=True)
        if "pai_health_system_access_proxy" not in frame:
            frame["pai_health_system_access_proxy"] = municipal_proxy
        else:
            frame["pai_health_system_access_proxy"] = municipal_proxy.fillna(
                frame["pai_health_system_access_proxy"]
            )
        municipal_available = municipal_proxy.notna()
        if "pai_proxy_territory_level" not in frame:
            frame["pai_proxy_territory_level"] = pd.NA
        frame.loc[municipal_available, "pai_proxy_territory_level"] = "municipality"

    deforestation = list(
        (
            await session.scalars(
                select(DeforestationObservation).where(
                    DeforestationObservation.municipality_code.in_(municipality_codes),
                    DeforestationObservation.year <= int(frame["year"].max()),
                )
            )
        ).all()
    )
    if deforestation:
        # Quarterly totals become an approximate weekly exposure. Repeating the
        # full quarterly total on every week would inflate rolling sums 13-fold.
        deforestation_frame = pd.DataFrame(
            [
                {
                    "territory_id": item.municipality_code,
                    "year": item.year,
                    "quarter": item.quarter,
                    "deforestation": (
                        item.deforested_hectares / 13.0
                        if item.deforested_hectares is not None
                        else None
                    ),
                    "deforestation_warnings": (
                        item.early_warning_count / 13.0
                        if item.early_warning_count is not None
                        else None
                    ),
                }
                for item in deforestation
            ]
        )
        frame = frame.merge(
            deforestation_frame,
            on=["territory_id", "year", "quarter"],
            how="left",
        )

    socioeconomic = list(
        (
            await session.scalars(
                select(SocioeconomicIndicator).where(
                    SocioeconomicIndicator.municipality_code.in_(municipality_codes),
                    SocioeconomicIndicator.year <= int(frame["year"].max()),
                )
            )
        ).all()
    )
    if socioeconomic:
        socioeconomic_frame = pd.DataFrame(
            [
                {
                    "territory_id": item.municipality_code,
                    "year": item.year,
                    "water_access": item.water_access_pct,
                    "sewer_access": item.sewer_access_pct,
                    "overcrowding": item.overcrowding_pct,
                    "nbi": item.nbi_pct,
                    "irca_index": item.irca_index,
                    "urban_population_pct": item.urban_population_pct,
                    "rural_population_pct": item.rural_population_pct,
                    "populated_center_population_pct": (
                        item.populated_center_population_pct
                    ),
                    "rural_remainder_population_pct": (
                        item.rural_remainder_population_pct
                    ),
                }
                for item in socioeconomic
            ]
        )
        # Explicit per-territory merge avoids merge_asof's global sort
        # assumptions and prevents one municipality crossing into another.
        pieces: list[pd.DataFrame] = []
        for territory, territory_frame in frame.groupby("territory_id", sort=True):
            indicators = socioeconomic_frame[socioeconomic_frame["territory_id"] == territory].drop(
                columns="territory_id"
            )
            if indicators.empty:
                pieces.append(territory_frame)
                continue
            pieces.append(
                pd.merge_asof(
                    territory_frame.sort_values("year"),
                    indicators.sort_values("year"),
                    on="year",
                    direction="backward",
                )
            )
        frame = pd.concat(pieces, ignore_index=True)

    frame = frame.sort_values(["territory_id", "week"])
    slow_columns = [
        column
        for column in frame.columns
        if column.startswith("pai_program_coverage_")
        or column.startswith("pai_municipal_coverage_")
        or column
        in {
            "pai_health_system_access_proxy",
            "deforestation",
            "deforestation_warnings",
            "water_access",
            "sewer_access",
            "overcrowding",
            "nbi",
            "urban_population_pct",
            "rural_population_pct",
            "populated_center_population_pct",
            "rural_remainder_population_pct",
        }
    ]
    if slow_columns:
        frame[slow_columns] = frame.groupby("territory_id", observed=True)[slow_columns].ffill()
    frame = frame.drop(columns=["year", "month", "quarter"], errors="ignore").reset_index(drop=True)
    fingerprint = frame_fingerprint(frame)
    all_records = [
        *observations,
        *climate,
        *vaccination,
        *municipal_vaccination,
        *deforestation,
        *socioeconomic,
    ]
    return TrainingDataset(
        frame=frame,
        fingerprint=fingerprint,
        manifest=_dataset_manifest(frame, disease, all_records, fingerprint),
    )


def frame_fingerprint(frame: pd.DataFrame) -> str:
    """Content-address a panel independently from row and column order."""

    return hashlib.sha256(canonical_frame_bytes(frame)).hexdigest()


def canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    canonical = frame.copy()
    columns = sorted(canonical.columns)
    canonical = canonical.reindex(columns=columns)
    for column in columns:
        if pd.api.types.is_datetime64_any_dtype(canonical[column]):
            canonical[column] = pd.to_datetime(canonical[column]).dt.strftime("%Y-%m-%d")
    sort_columns = [
        column for column in ("disease", "territory_id", "week") if column in canonical.columns
    ]
    if sort_columns:
        canonical = canonical.sort_values(sort_columns, kind="mergesort")
    payload = canonical.to_csv(
        index=False,
        columns=columns,
        na_rep="__NULL__",
        float_format="%.12g",
        lineterminator="\n",
    )
    return payload.encode("utf-8")


def persist_training_dataset(
    dataset: TrainingDataset,
    registry_root: str | Path,
) -> DatasetSnapshot:
    """Persist a deterministic compressed CSV and lineage manifest once."""

    root = Path(registry_root).expanduser().resolve() / "datasets" / dataset.manifest["disease"]
    if os.name == "nt":
        # Python's Windows filesystem calls still need the extended-length
        # prefix when a configured registry root plus a SHA-256 identifier
        # exceeds MAX_PATH (common in CI/test workspaces).
        raw_root = str(root)
        if not raw_root.startswith("\\\\?\\"):
            root = Path(f"\\\\?\\{raw_root}")
    target = root / dataset.fingerprint
    data_path = target / "panel.csv.gz"
    manifest_path = target / "manifest.json"
    if data_path.exists() and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = str(existing.get("snapshot_sha256", ""))
        if expected and _file_sha256(data_path) != expected:
            raise OSError(f"Dataset snapshot checksum mismatch: {data_path}")
        return DatasetSnapshot(str(data_path), expected, str(manifest_path))

    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{dataset.fingerprint}.{uuid4().hex}.tmp"
    # Keep this defensive even though ``root`` was created above. Some test and
    # worker environments mount/clean the registry parent between filesystem
    # operations; recreating the parent here preserves the atomic-write contract.
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=False, exist_ok=False)
    try:
        compressed_path = temporary / "panel.csv.gz"
        with compressed_path.open("wb") as raw:
            with gzip.GzipFile(filename="panel.csv", mode="wb", fileobj=raw, mtime=0) as stream:
                stream.write(canonical_frame_bytes(dataset.frame))
        snapshot_hash = _file_sha256(compressed_path)
        manifest = {
            **dataset.manifest,
            "snapshot_sha256": snapshot_hash,
            "snapshot_format": "csv.gz",
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.replace(temporary, target)
        except OSError as publication_error:
            # Another worker may have won the content-addressed publication
            # race. A completed, checksum-valid target is equivalent; any other
            # filesystem error remains fatal.
            if not data_path.exists() or not manifest_path.exists():
                raise
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = str(existing.get("snapshot_sha256", ""))
            if not expected or _file_sha256(data_path) != expected:
                raise OSError(
                    f"Dataset snapshot checksum mismatch: {data_path}"
                ) from publication_error
            shutil.rmtree(temporary)
            snapshot_hash = expected
        return DatasetSnapshot(str(data_path), snapshot_hash, str(manifest_path))
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _calendarize(observed: pd.DataFrame, disease: str) -> pd.DataFrame:
    calendars = []
    for territory, group in observed.groupby("territory_id", sort=True):
        calendar = pd.DataFrame(
            {
                "territory_id": territory,
                "week": pd.date_range(group["week"].min(), group["week"].max(), freq="7D"),
            }
        )
        calendars.append(calendar)
    grid = pd.concat(calendars, ignore_index=True)
    result = grid.merge(observed, on=["territory_id", "week"], how="left")
    result["disease"] = result["disease"].fillna(disease)
    return result


def _dataset_manifest(
    frame: pd.DataFrame,
    disease: str,
    records: list[Any],
    fingerprint: str,
) -> dict[str, Any]:
    source_ids = sorted(
        {str(record.source_id) for record in records if getattr(record, "source_id", None)}
    )
    ingestion_runs = sorted(
        {
            str(record.ingestion_run_id)
            for record in records
            if getattr(record, "ingestion_run_id", None)
        }
    )
    cases = frame["cases"] if "cases" in frame else pd.Series(dtype=float)
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "disease": disease,
        "fingerprint": fingerprint,
        "extracted_at": datetime.now(UTC).isoformat(),
        "rows": int(len(frame)),
        "observed_case_rows": int(cases.notna().sum()),
        "missing_case_weeks": int(cases.isna().sum()),
        "territories": int(frame["territory_id"].nunique()) if "territory_id" in frame else 0,
        "week_start": _date_string(frame["week"].min()) if len(frame) else None,
        "week_end": _date_string(frame["week"].max()) if len(frame) else None,
        "columns": sorted(frame.columns.tolist()),
        "source_ids": source_ids,
        "ingestion_run_ids": ingestion_runs,
        "temporal_join_policy": "effective-period backward-only; no target backfill",
        "missing_case_policy": "calendarized NaN; never coerced to zero",
        "covariate_granularity": {
            "pai_health_system_access_proxy": (
                "municipality/month cut-off joined backward from next month; "
                "department/year is an explicit fallback"
            ),
            "climate": "municipality/week",
            "deforestation": "municipality/quarter converted to weekly exposure",
            "socioeconomic": "municipality/year backward-only",
        },
        "feature_semantics": {
            "pai_health_system_access_proxy": {
                "role": "health_system_access_proxy",
                "causal_interpretation": False,
                "limitation": (
                    "PAI BCG/PENTA/N2D/TV coverages are not disease-specific protection "
                    "for dengue, malaria, chikunguna, zika or leishmaniasis"
                ),
                "direct_vaccine_policy": (
                    "direct protection features require disease-specific validation; "
                    "the available infant influenza series is not direct protection "
                    "for an all-age IRA outcome"
                ),
            },
            "urban_population_pct": {
                "role": "structural_territorial_composition",
                "source": "DANE CNPV 2018 layer 801",
                "definition": "CLAS_CCDGO 1 cabecera / population in classes 1+2+3",
                "causal_interpretation": False,
            },
            "rural_population_pct": {
                "role": "structural_territorial_composition",
                "source": "DANE CNPV 2018 layer 801",
                "definition": (
                    "CLAS_CCDGO 2 centro poblado + 3 area resto / "
                    "population in classes 1+2+3"
                ),
                "causal_interpretation": False,
            },
        },
        "covariate_coverage": _covariate_coverage(frame),
        "known_data_gaps": _known_data_gaps(frame),
    }


def _covariate_coverage(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    groups = {
        "climate": ["precipitation", "temperature", "humidity"],
        "pai_municipal": [
            column for column in frame if column.startswith("pai_municipal_coverage_")
        ],
        "pai_proxy": ["pai_health_system_access_proxy"],
        "deforestation": ["deforestation", "deforestation_warnings"],
        "socioeconomic": ["water_access", "sewer_access", "overcrowding", "nbi"],
        "population": ["population"],
        "urban_rural": [
            "urban_population_pct",
            "rural_population_pct",
            "populated_center_population_pct",
            "rural_remainder_population_pct",
        ],
    }
    rows = max(1, len(frame))
    result: dict[str, dict[str, Any]] = {}
    for group, expected_columns in groups.items():
        present = [column for column in expected_columns if column in frame]
        populated = [column for column in present if frame[column].notna().any()]
        per_column = {
            column: {
                "non_null_rows": int(frame[column].notna().sum()),
                "coverage_pct": round(float(frame[column].notna().sum() * 100 / rows), 3),
            }
            for column in present
        }
        result[group] = {
            "status": (
                "unavailable"
                if not populated
                else "partial"
                if len(populated) < len(expected_columns)
                or any(item["coverage_pct"] < 95.0 for item in per_column.values())
                else "available"
            ),
            "expected_columns": expected_columns,
            "populated_columns": populated,
            "columns": per_column,
        }
    return result


def _known_data_gaps(frame: pd.DataFrame) -> list[dict[str, str]]:
    coverage = _covariate_coverage(frame)
    descriptions = {
        "climate": "La cobertura climatica semanal no cubre todo el periodo epidemiologico.",
        "deforestation": "No hay una serie municipal versionada de deforestacion disponible.",
        "socioeconomic": "CNPV 2018 es estructural; hacinamiento y NBI no estan poblados.",
        "urban_rural": (
            "La composicion urbano-rural CNPV 2018 es estructural y puede no cubrir "
            "todos los municipios o periodos posteriores."
        ),
    }
    return [
        {"covariate": group, "status": details["status"], "limitation": descriptions[group]}
        for group, details in coverage.items()
        if group in descriptions and details["status"] != "available"
    ]


def _date_string(value: Any) -> str:
    return pd.Timestamp(value).date().isoformat()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
