"""Validation and idempotent canonical persistence for official aggregate sources."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.sivigila import EVENT_TO_DISEASE
from app.ingestion.divipola import normalize_name
from app.ingestion.normalizers import normalize_pai, normalize_sivigila
from app.ingestion.pai_files import PAIMunicipalRecord
from app.ingestion.snapshots import SnapshotArtifact
from app.models.epidemiology import (
    ClimateObservation,
    DepartmentVaccinationCoverage,
    EpidemiologicalObservation,
    IngestionRun,
    Municipality,
    QuarantineRecord,
    RawSnapshot,
    SocioeconomicIndicator,
    VaccinationCoverage,
    WeatherStation,
)


class CanonicalValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SIVIGILACanonical:
    municipality_code: str
    disease: str
    week_start: date
    epidemiological_week: int
    epidemiological_year: int
    cases: int
    raw_record_sha256: str


@dataclass(frozen=True, slots=True)
class PAICanonical:
    department_code: str
    department_name: str
    year: int
    vaccine: str
    source_vaccine_label: str
    coverage_pct: float
    raw_record_sha256: str


@dataclass(frozen=True, slots=True)
class CNPVClassCanonical:
    municipality_code: str
    class_code: str
    population: float


@dataclass(slots=True)
class ClimateBucket:
    station_values: dict[str, list[tuple[float, int]]] = field(default_factory=dict)

    def add(self, station: str, value: float, reading_count: int) -> None:
        self.station_values.setdefault(station, []).append((value, max(1, reading_count)))

    def result(self, metric: str) -> tuple[float, int]:
        if metric == "precipitation":
            station_week_totals = [
                sum(value for value, _ in readings)
                for readings in self.station_values.values()
            ]
            return sum(station_week_totals) / len(station_week_totals), len(
                station_week_totals
            )
        weighted_sum = sum(
            value * count
            for readings in self.station_values.values()
            for value, count in readings
        )
        count = sum(
            count for readings in self.station_values.values() for _, count in readings
        )
        return weighted_sum / count, len(self.station_values)


@dataclass(slots=True)
class MunicipalityResolver:
    by_code: dict[str, Municipality]
    by_name: dict[tuple[str, str], Municipality]

    @classmethod
    async def load(cls, session: AsyncSession) -> MunicipalityResolver:
        municipalities = list((await session.scalars(select(Municipality))).all())
        return cls(
            by_code={item.code: item for item in municipalities},
            by_name={
                (normalize_name(item.department_name), normalize_name(item.name)): item
                for item in municipalities
            },
        )

    def names(self, department: Any, municipality: Any) -> Municipality | None:
        if not department or not municipality:
            return None
        return self.by_name.get(
            (normalize_name(str(department)), normalize_name(str(municipality)))
        )


def raw_record_sha256(row: dict[str, Any]) -> str:
    encoded = json.dumps(
        row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def epidemiological_week_start(year: int, week: int) -> date:
    """INS week: Sunday-Saturday; week 1 contains January 4."""
    if week < 1 or week > 53:
        raise CanonicalValidationError("invalid_week", "Semana epidemiológica fuera de 1..53")
    january_fourth = date(year, 1, 4)
    sunday_offset = (january_fourth.weekday() + 1) % 7
    return january_fourth - timedelta(days=sunday_offset) + timedelta(weeks=week - 1)


_TERRITORIAL_OPEN_SOURCE_PREFIXES = (
    "sivigila-boyaca-",
    "sivigila-caqueta-",
    "sivigila-pereira-",
    "sivigila-tulua-",
    "sivigila-bucaramanga-",
    "sivigila-casanare-",
    "sivigila-santa-rosa-",
    "sivigila-territorial-",
)


def _is_territorial_open_source(source_id: str) -> bool:
    return source_id.startswith(_TERRITORIAL_OPEN_SOURCE_PREFIXES) or source_id in {
        "sivigila-territorial-open",
        "sivigila-boyaca-events",
        "sivigila-caqueta-dengue",
        "sivigila-pereira-dengue",
        "sivigila-tulua-dengue",
        "sivigila-bucaramanga-dengue",
        "sivigila-bucaramanga-events",
        "sivigila-bucaramanga-ira",
        "sivigila-casanare-dengue",
        "sivigila-santa-rosa-cabal-events",
    }


def _should_replace_observation(
    *,
    stored_year: int,
    stored_source_id: str,
    incoming_year: int,
    incoming_source_id: str,
) -> bool:
    """Decide whether an incoming municipio/semana row may overwrite storage."""

    if incoming_year > stored_year:
        return True
    if incoming_year < stored_year:
        return False
    # Same year: keep territorial open data ahead of national historical backfill.
    if _is_territorial_open_source(stored_source_id) and incoming_source_id in {
        "sivigila-national",
        "sivigila-microdata-2024",
    }:
        return False
    return True


def canonicalize_sivigila(row: dict[str, Any]) -> SIVIGILACanonical:
    observation, quality = normalize_sivigila(row)
    if not quality.valid:
        raise CanonicalValidationError(
            "quality_error", "; ".join(issue.message for issue in quality.issues)
        )
    try:
        event_code = int(observation.event_code)
    except ValueError as exc:
        raise CanonicalValidationError("invalid_event_code", str(exc)) from exc
    disease = EVENT_TO_DISEASE.get(event_code)
    if disease is None:
        raise CanonicalValidationError(
            "event_not_prioritized", f"Evento INS {event_code} fuera del alcance PRORA"
        )
    municipality_code = observation.territory.divipola_code
    if municipality_code is None:
        raise CanonicalValidationError("missing_divipola", "No se pudo construir DIVIPOLA")
    return SIVIGILACanonical(
        municipality_code=municipality_code,
        disease=disease,
        week_start=epidemiological_week_start(
            observation.epidemiological_year, observation.epidemiological_week
        ),
        epidemiological_week=observation.epidemiological_week,
        epidemiological_year=observation.epidemiological_year,
        cases=observation.cases,
        raw_record_sha256=observation.provenance.raw_record_sha256,
    )


async def upsert_sivigila(
    session: AsyncSession,
    run: IngestionRun,
    resolver: MunicipalityResolver,
    item: SIVIGILACanonical,
) -> None:
    municipality = resolver.by_code.get(item.municipality_code)
    if municipality is None:
        raise CanonicalValidationError(
            "unknown_divipola", f"DIVIPOLA no registrado: {item.municipality_code}"
        )
    stored = await session.scalar(
        select(EpidemiologicalObservation).where(
            EpidemiologicalObservation.municipality_code == item.municipality_code,
            EpidemiologicalObservation.disease == item.disease,
            EpidemiologicalObservation.week_start == item.week_start,
        )
    )
    population = municipality.population
    values = {
        "epidemiological_week": item.epidemiological_week,
        "epidemiological_year": item.epidemiological_year,
        "cases": item.cases,
        "population": population,
        "incidence_per_100k": item.cases * 100_000 / population if population else None,
        "is_preliminary": False,
        "quality_score": 0.85 if item.disease == "ira" else 1.0,
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if stored is None:
        session.add(
            EpidemiologicalObservation(
                municipality_code=item.municipality_code,
                disease=item.disease,
                week_start=item.week_start,
                **values,
            )
        )
    else:
        for key, value in values.items():
            setattr(stored, key, value)


async def upsert_sivigila_batch(
    session: AsyncSession,
    run: IngestionRun,
    resolver: MunicipalityResolver,
    items: list[SIVIGILACanonical],
) -> None:
    """Preload the target slice once instead of issuing one SELECT per observation."""
    if not items:
        return
    minimum_week = min(item.week_start for item in items)
    maximum_week = max(item.week_start for item in items)
    diseases = sorted({item.disease for item in items})
    existing = list(
        (
            await session.scalars(
                select(EpidemiologicalObservation).where(
                    EpidemiologicalObservation.week_start >= minimum_week,
                    EpidemiologicalObservation.week_start <= maximum_week,
                    EpidemiologicalObservation.disease.in_(diseases),
                )
            )
        ).all()
    )
    by_key = {
        (item.municipality_code, item.disease, item.week_start): item for item in existing
    }
    for item in items:
        municipality = resolver.by_code[item.municipality_code]
        key = (item.municipality_code, item.disease, item.week_start)
        stored = by_key.get(key)
        population = municipality.population
        values = {
            "epidemiological_week": item.epidemiological_week,
            "epidemiological_year": item.epidemiological_year,
            "cases": item.cases,
            "population": population,
            "incidence_per_100k": item.cases * 100_000 / population if population else None,
            "is_preliminary": False,
            "quality_score": 0.85 if item.disease == "ira" else 1.0,
            "source_id": run.source_id,
            "ingestion_run_id": run.id,
        }
        if stored is None:
            stored = EpidemiologicalObservation(
                municipality_code=item.municipality_code,
                disease=item.disease,
                week_start=item.week_start,
                **values,
            )
            session.add(stored)
            by_key[key] = stored
        else:
            if not _should_replace_observation(
                stored_year=int(stored.epidemiological_year or 0),
                stored_source_id=str(stored.source_id or ""),
                incoming_year=int(item.epidemiological_year or 0),
                incoming_source_id=str(run.source_id or ""),
            ):
                continue
            for field_name, value in values.items():
                setattr(stored, field_name, value)


def _repair_text(value: Any) -> str:
    text = str(value).strip()
    if "Ã" in text or "Â" in text:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_vaccine(source_label: str) -> str:
    repaired = _repair_text(source_label)
    key = normalize_name(repaired)
    if "TRIPLE VIRAL" in key or re.search(r"\bSRP\b", key):
        return "Triple viral (SRP)"
    if "FIEBRE AMARILLA" in key:
        return "Fiebre amarilla"
    if "INFLUENZA" in key:
        return "Influenza"
    return repaired


def canonicalize_pai(row: dict[str, Any]) -> PAICanonical:
    observation, quality = normalize_pai(row)
    if not quality.valid:
        raise CanonicalValidationError(
            "quality_error", "; ".join(issue.message for issue in quality.issues)
        )
    department_code = observation.territory.department_code
    department_name = observation.territory.department_name
    if department_code is None or department_name is None:
        raise CanonicalValidationError(
            "missing_department", "PAI no contiene departamento canónico"
        )
    source_label = str(row.get("biol_gico") or observation.biologic)
    return PAICanonical(
        department_code=department_code,
        department_name=_repair_text(department_name),
        year=observation.year,
        vaccine=_canonical_vaccine(source_label),
        source_vaccine_label=source_label,
        coverage_pct=observation.coverage_percent,
        raw_record_sha256=observation.provenance.raw_record_sha256,
    )


async def upsert_pai(session: AsyncSession, run: IngestionRun, item: PAICanonical) -> None:
    stored = await session.scalar(
        select(DepartmentVaccinationCoverage).where(
            DepartmentVaccinationCoverage.department_code == item.department_code,
            DepartmentVaccinationCoverage.year == item.year,
            DepartmentVaccinationCoverage.vaccine == item.vaccine,
        )
    )
    values = {
        "department_name": item.department_name,
        "territory_level": "department",
        "coverage_pct": item.coverage_pct,
        "source_vaccine_label": item.source_vaccine_label,
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
        "raw_record_sha256": item.raw_record_sha256,
    }
    if stored is None:
        session.add(
            DepartmentVaccinationCoverage(
                department_code=item.department_code,
                year=item.year,
                vaccine=item.vaccine,
                **values,
            )
        )
    else:
        for key, value in values.items():
            setattr(stored, key, value)


def climate_week_key(
    row: dict[str, Any], resolver: MunicipalityResolver
) -> tuple[str, date, str, float, int]:
    municipality = resolver.names(row.get("departamento"), row.get("municipio"))
    if municipality is None:
        raise CanonicalValidationError(
            "unknown_territory",
            f"Territorio IDEAM no resuelto: {row.get('departamento')}/{row.get('municipio')}",
        )
    try:
        observed = datetime.fromisoformat(str(row["observation_day"]).replace("Z", "+00:00"))
        value = float(row["metric_value"])
        reading_count = int(row.get("reading_count") or 1)
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalValidationError("invalid_climate_aggregate", str(exc)) from exc
    day = observed.date()
    sunday = day - timedelta(days=(day.weekday() + 1) % 7)
    station = str(row.get("codigoestacion") or "unknown").strip()
    return municipality.code, sunday, station, value, reading_count


async def upsert_climate_bucket(
    session: AsyncSession,
    run: IngestionRun,
    municipality_code: str,
    week_start: date,
    metric: str,
    bucket: ClimateBucket,
    snapshot_sha256: str,
) -> None:
    value, station_count = bucket.result(metric)
    stored = await session.scalar(
        select(ClimateObservation).where(
            ClimateObservation.municipality_code == municipality_code,
            ClimateObservation.week_start == week_start,
        )
    )
    if stored is None:
        stored = ClimateObservation(
            municipality_code=municipality_code,
            week_start=week_start,
            source_id=run.source_id,
            ingestion_run_id=run.id,
            metric_provenance={},
        )
        session.add(stored)
    _apply_climate_bucket(
        stored, run, metric, value, station_count, snapshot_sha256
    )


async def upsert_climate_buckets(
    session: AsyncSession,
    run: IngestionRun,
    buckets: dict[tuple[str, date], ClimateBucket],
    metric: str,
    snapshot_sha256: str,
) -> None:
    if not buckets:
        return
    minimum_week = min(week for _, week in buckets)
    maximum_week = max(week for _, week in buckets)
    existing = list(
        (
            await session.scalars(
                select(ClimateObservation).where(
                    ClimateObservation.week_start >= minimum_week,
                    ClimateObservation.week_start <= maximum_week,
                )
            )
        ).all()
    )
    by_key = {(item.municipality_code, item.week_start): item for item in existing}
    for (municipality_code, week_start), bucket in buckets.items():
        key = (municipality_code, week_start)
        stored = by_key.get(key)
        if stored is None:
            stored = ClimateObservation(
                municipality_code=municipality_code,
                week_start=week_start,
                source_id=run.source_id,
                ingestion_run_id=run.id,
                metric_provenance={},
            )
            session.add(stored)
            by_key[key] = stored
        value, station_count = bucket.result(metric)
        _apply_climate_bucket(
            stored, run, metric, value, station_count, snapshot_sha256
        )


def _apply_climate_bucket(
    stored: ClimateObservation,
    run: IngestionRun,
    metric: str,
    value: float,
    station_count: int,
    snapshot_sha256: str,
) -> None:
    if metric == "precipitation":
        stored.precipitation_mm = value
    elif metric == "temperature":
        stored.temperature_mean_c = value
    elif metric == "humidity":
        if value < 0 or value > 100:
            raise CanonicalValidationError("humidity_out_of_range", f"Humedad={value}")
        stored.humidity_relative_pct = value
    else:
        raise CanonicalValidationError("unsupported_metric", metric)
    stored.station_count = max(stored.station_count or 0, station_count)
    stored.interpolation_method = "IDEAM station/day aggregate; PRORA Sunday-week rollup"
    stored.quality_score = 1.0
    stored.source_id = run.source_id
    stored.ingestion_run_id = run.id
    provenance = dict(stored.metric_provenance or {})
    provenance[metric] = {
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
        "snapshot_sha256": snapshot_sha256,
        "aggregation": "station-day then municipality-week",
    }
    stored.metric_provenance = provenance


async def upsert_irca_batch(
    session: AsyncSession,
    run: IngestionRun,
    items: list[tuple[str, int, float]],
) -> None:
    """Upsert municipal IRCA values without erasing CNPV water/sewer indicators."""

    if not items:
        return
    codes = sorted({code for code, _, _ in items})
    years = sorted({year for _, year, _ in items})
    existing = list(
        (
            await session.scalars(
                select(SocioeconomicIndicator).where(
                    SocioeconomicIndicator.municipality_code.in_(codes),
                    SocioeconomicIndicator.year.in_(years),
                )
            )
        ).all()
    )
    by_key = {(item.municipality_code, item.year): item for item in existing}
    for municipality_code, year, irca in items:
        key = (municipality_code, year)
        stored = by_key.get(key)
        if stored is None:
            stored = SocioeconomicIndicator(
                municipality_code=municipality_code,
                year=year,
                irca_index=irca,
                source_id=run.source_id,
                ingestion_run_id=run.id,
            )
            session.add(stored)
            by_key[key] = stored
            continue
        stored.irca_index = irca
        # Keep CNPV structural fields; only retag source when row was IRCA-created.
        if stored.source_id in {None, "", run.source_id, "ins-irca-water-quality"}:
            stored.source_id = run.source_id
            stored.ingestion_run_id = run.id


async def upsert_municipal_pai_batch(
    session: AsyncSession,
    run: IngestionRun,
    records: list[PAIMunicipalRecord],
) -> None:
    if not records:
        return
    minimum_year = min(record.year for record in records)
    maximum_year = max(record.year for record in records)
    vaccines = sorted({record.vaccine for record in records})
    existing = list(
        (
            await session.scalars(
                select(VaccinationCoverage).where(
                    VaccinationCoverage.year >= minimum_year,
                    VaccinationCoverage.year <= maximum_year,
                    VaccinationCoverage.vaccine.in_(vaccines),
                )
            )
        ).all()
    )
    by_key = {
        (item.municipality_code, item.year, item.month, item.vaccine): item
        for item in existing
    }
    for record in records:
        key = (
            record.municipality_code,
            record.year,
            record.month,
            record.vaccine,
        )
        stored = by_key.get(key)
        payload = record.payload()
        values = {
            "source_vaccine_label": record.source_label,
            "period_semantics": (
                "annual_cutoff"
                if record.month == 12 and record.year < 2026
                else "cumulative_cutoff"
            ),
            "target_population": None,
            "doses_applied": record.doses_applied,
            "coverage_pct": record.coverage_pct,
            "source_id": run.source_id,
            "ingestion_run_id": run.id,
            "raw_record_sha256": raw_record_sha256(payload),
        }
        if stored is None:
            stored = VaccinationCoverage(
                municipality_code=record.municipality_code,
                year=record.year,
                month=record.month,
                vaccine=record.vaccine,
                **values,
            )
            session.add(stored)
            by_key[key] = stored
        else:
            for field_name, value in values.items():
                setattr(stored, field_name, value)


async def upsert_station(
    session: AsyncSession,
    run: IngestionRun,
    resolver: MunicipalityResolver,
    row: dict[str, Any],
) -> bool:
    code = str(row.get("codigo") or "").strip()
    name = _repair_text(row.get("nombre") or "")
    if not code or not name:
        raise CanonicalValidationError("missing_station_identity", "Código/nombre requerido")
    latitude = _optional_float(row.get("latitud"))
    longitude = _optional_float(row.get("longitud"))
    if latitude is not None and not -4.5 <= latitude <= 13.7:
        raise CanonicalValidationError("latitude_out_of_range", f"latitud={latitude}")
    if longitude is not None and not -82 <= longitude <= -66.5:
        raise CanonicalValidationError("longitude_out_of_range", f"longitud={longitude}")
    municipality = resolver.names(row.get("departamento"), row.get("municipio"))
    stored = await session.get(WeatherStation, code)
    values = {
        "name": name,
        "category": _optional_text(row.get("categoria")),
        "technology": _optional_text(row.get("tecnologia")),
        "operational_status": _optional_text(row.get("estado")),
        "department_name": _optional_text(row.get("departamento")),
        "municipality_name": _optional_text(row.get("municipio")),
        "municipality_code": municipality.code if municipality else None,
        "latitude": latitude,
        "longitude": longitude,
        "elevation_m": _optional_float(row.get("altitud")),
        "provider": _optional_text(row.get("entidad")),
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
        "raw_record_sha256": raw_record_sha256(row),
    }
    if stored is None:
        session.add(WeatherStation(code=code, **values))
    else:
        for key, value in values.items():
            setattr(stored, key, value)
    return municipality is not None


async def upsert_cnpv(
    session: AsyncSession,
    run: IngestionRun,
    resolver: MunicipalityResolver,
    row: dict[str, Any],
    class_population: dict[str, float] | None = None,
) -> None:
    code = str(row.get("MPIO_CDPMP") or "").strip().zfill(5)
    municipality = resolver.by_code.get(code)
    if municipality is None:
        raise CanonicalValidationError("unknown_divipola", f"DIVIPOLA no registrado: {code}")
    water_yes = _required_nonnegative(row, "STP19_ACU1")
    water_no = _required_nonnegative(row, "STP19_ACU2")
    sewer_yes = _required_nonnegative(row, "STP19_ALC1")
    sewer_no = _required_nonnegative(row, "STP19_ALC2")
    population = int(_required_nonnegative(row, "STP27_PERS"))
    water_denominator = water_yes + water_no
    sewer_denominator = sewer_yes + sewer_no
    if not water_denominator or not sewer_denominator:
        raise CanonicalValidationError("zero_denominator", "CNPV sin denominador de vivienda")
    stored = await session.scalar(
        select(SocioeconomicIndicator).where(
            SocioeconomicIndicator.municipality_code == code,
            SocioeconomicIndicator.year == 2018,
        )
    )
    values = {
        "water_access_pct": water_yes * 100 / water_denominator,
        "sewer_access_pct": sewer_yes * 100 / sewer_denominator,
        "source_id": run.source_id,
        "ingestion_run_id": run.id,
    }
    if class_population:
        class_total = sum(class_population.get(class_code, 0.0) for class_code in ("1", "2", "3"))
        if class_total <= 0:
            raise CanonicalValidationError(
                "zero_class_population",
                "CNPV capa 801 sin denominador poblacional para clases 1, 2 y 3",
            )
        urban = class_population.get("1", 0.0)
        populated_center = class_population.get("2", 0.0)
        rural_remainder = class_population.get("3", 0.0)
        values.update(
            {
                "urban_population_pct": urban * 100 / class_total,
                "rural_population_pct": (
                    (populated_center + rural_remainder) * 100 / class_total
                ),
                "populated_center_population_pct": populated_center * 100 / class_total,
                "rural_remainder_population_pct": rural_remainder * 100 / class_total,
            }
        )
    if stored is None:
        session.add(SocioeconomicIndicator(municipality_code=code, year=2018, **values))
    else:
        for key, value in values.items():
            setattr(stored, key, value)
    municipality.population = population


def canonicalize_cnpv_class(row: dict[str, Any]) -> CNPVClassCanonical:
    code = str(row.get("MPIO_CDPMP") or "").strip().zfill(5)
    if len(code) != 5 or not code.isdigit():
        raise CanonicalValidationError("invalid_divipola", f"Código CNPV inválido: {code}")
    class_code = str(row.get("CLAS_CCDGO") or "").strip()
    if class_code not in {"1", "2", "3"}:
        raise CanonicalValidationError(
            "invalid_cnpv_class",
            f"CLAS_CCDGO fuera del contrato 1/2/3: {class_code}",
        )
    return CNPVClassCanonical(
        municipality_code=code,
        class_code=class_code,
        population=_required_nonnegative(row, "STP27_PERS"),
    )


async def add_quarantine(
    session: AsyncSession,
    run: IngestionRun,
    row_number: int,
    row: dict[str, Any],
    error: CanonicalValidationError,
) -> None:
    safe_payload = json.loads(
        json.dumps(_finite_json(row), ensure_ascii=False, default=str, allow_nan=False)
    )
    session.add(
        QuarantineRecord(
            ingestion_run_id=run.id,
            source_id=run.source_id,
            row_number=row_number,
            raw_record_sha256=raw_record_sha256(row),
            reason_code=error.code,
            reason=str(error)[:2000],
            raw_payload=safe_payload,
        )
    )


def _finite_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def store_snapshot(session: AsyncSession, run: IngestionRun, artifact: SnapshotArtifact) -> None:
    session.add(
        RawSnapshot(
            ingestion_run_id=run.id,
            source_id=run.source_id,
            object_path=artifact.object_path,
            manifest_path=artifact.manifest_path,
            media_type=artifact.media_type,
            content_bytes=artifact.content_bytes,
            row_count=artifact.row_count,
            page_count=artifact.page_count,
            sha256=artifact.sha256,
            schema_sha256=artifact.schema_sha256,
            manifest=artifact.manifest,
            retrieved_at=artifact.retrieved_at,
        )
    )


def _required_nonnegative(row: dict[str, Any], field_name: str) -> float:
    try:
        value = float(row[field_name])
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalValidationError("invalid_cnpv_value", f"{field_name}: {exc}") from exc
    if value < 0:
        raise CanonicalValidationError("negative_cnpv_value", f"{field_name}={value}")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _repair_text(value)
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalValidationError("invalid_number", str(exc)) from exc
