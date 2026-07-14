"""Public inventory of configured sources and data actually persisted by PRORA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import (
    ClimateObservation,
    DataSource,
    DeforestationObservation,
    DepartmentVaccinationCoverage,
    EpidemiologicalBulletinAggregate,
    EpidemiologicalObservation,
    IngestionRun,
    Municipality,
    PipelineStatus,
    RawSnapshot,
    SocioeconomicIndicator,
    SourceStatus,
    VaccinationCoverage,
    WeatherStation,
)
from app.schemas.sources import StoredDatasetInventory


@dataclass(frozen=True, slots=True)
class InventoryMeasure:
    table: str
    territory: str
    temporal: str
    statement: Select[tuple[Any, ...]]
    period_kind: str = "date"
    semantics: str = "Filas canónicas vinculadas a esta fuente."


def _measures() -> dict[str, InventoryMeasure]:
    return {
        "dane-divipola": InventoryMeasure(
            "municipalities",
            "municipality",
            "vintage",
            select(func.count()).select_from(Municipality),
            "none",
            "Directorio territorial DIVIPOLA; la tabla no mezcla observaciones sanitarias.",
        ),
        "sivigila-national": InventoryMeasure(
            "epidemiological_observations",
            "municipality",
            "epidemiological_week",
            select(
                func.count(),
                func.min(EpidemiologicalObservation.week_start),
                func.max(EpidemiologicalObservation.week_start),
            ).where(EpidemiologicalObservation.source_id == "sivigila-national"),
            semantics=(
                "Agregados INS municipio/semana hasta 2022; IRAG 348 es proxy explícito de IRA."
            ),
        ),
        "sivigila-current-authorized": InventoryMeasure(
            "epidemiological_observations",
            "municipality",
            "epidemiological_week",
            select(
                func.count(),
                func.min(EpidemiologicalObservation.week_start),
                func.max(EpidemiologicalObservation.week_start),
            ).where(
                EpidemiologicalObservation.source_id == "sivigila-current-authorized"
            ),
            semantics=(
                "Carga agregada 2023+ autorizada por INS; nunca se mezcla con microdatos "
                "ni se presenta como API pública."
            ),
        ),
        "ins-bes-weekly": InventoryMeasure(
            "epidemiological_bulletin_aggregates",
            "department_or_certified_district",
            "epidemiological_week",
            select(
                func.count(),
                func.min(EpidemiologicalBulletinAggregate.period_end),
                func.max(EpidemiologicalBulletinAggregate.period_end),
            ).where(EpidemiologicalBulletinAggregate.source_id == "ins-bes-weekly"),
            semantics=(
                "Referencia oficial reciente del BES; conserva acumulados y comparaciones "
                "por entidad territorial sin imputarlos a municipios ni al panel de entrenamiento."
            ),
        ),
        "pai-national": InventoryMeasure(
            "department_vaccination_coverages",
            "department",
            "year",
            select(
                func.count(),
                func.min(DepartmentVaccinationCoverage.year),
                func.max(DepartmentVaccinationCoverage.year),
            ).where(DepartmentVaccinationCoverage.source_id == "pai-national"),
            "year",
            "Cobertura administrativa departamental; no se replica a municipios.",
        ),
        "pai-municipal-history": InventoryMeasure(
            "vaccination_coverages",
            "municipality",
            "year",
            select(
                func.count(),
                func.min(VaccinationCoverage.year),
                func.max(VaccinationCoverage.year),
            ).where(VaccinationCoverage.source_id == "pai-municipal-history"),
            "year",
            "Cortes anuales municipales extraídos del archivo oficial 1998–2025.",
        ),
        "pai-municipal-2026": InventoryMeasure(
            "vaccination_coverages",
            "municipality",
            "month_cutoff",
            select(
                func.count(),
                func.min(VaccinationCoverage.year * 100 + VaccinationCoverage.month),
                func.max(VaccinationCoverage.year * 100 + VaccinationCoverage.month),
            ).where(VaccinationCoverage.source_id == "pai-municipal-2026"),
            "year_month",
            (
                "Cortes acumulados enero/febrero de 2026; no se interpreta como "
                "serie mensual completa."
            ),
        ),
        "ideam-stations": InventoryMeasure(
            "weather_stations",
            "station",
            "catalog",
            select(func.count()).select_from(WeatherStation).where(
                WeatherStation.source_id == "ideam-stations"
            ),
            "none",
            "Catálogo de estaciones; no equivale a cobertura censal de municipios.",
        ),
        "dane-socioeconomic": InventoryMeasure(
            "socioeconomic_indicators",
            "municipality",
            "census_vintage",
            select(
                func.count(),
                func.min(SocioeconomicIndicator.year),
                func.max(SocioeconomicIndicator.year),
            ).where(SocioeconomicIndicator.source_id == "dane-socioeconomic"),
            "year",
            (
                "Indicadores estructurales CNPV 2018. Agua, alcantarillado y poblacion "
                "provienen de capa 800; composicion por cabecera, centro poblado y area "
                "resto proviene de capa 801. No son mediciones actuales."
            ),
        ),
        "ideam-deforestation": InventoryMeasure(
            "deforestation_observations",
            "municipality",
            "quarter",
            select(
                func.count(),
                func.min(DeforestationObservation.year),
                func.max(DeforestationObservation.year),
            ).where(DeforestationObservation.source_id == "ideam-deforestation"),
            "year",
            "Sin filas hasta aprobar un contrato geoespacial y su unidad de medida.",
        ),
        "ideam-precipitation": _climate_measure(
            "precipitation_mm", ClimateObservation.precipitation_mm
        ),
        "ideam-temperature": _climate_measure(
            "temperature_mean_c", ClimateObservation.temperature_mean_c
        ),
        "ideam-humidity": _climate_measure(
            "humidity_relative_pct", ClimateObservation.humidity_relative_pct
        ),
    }


def _climate_measure(metric: str, column: Any) -> InventoryMeasure:
    return InventoryMeasure(
        "climate_observations",
        "municipality_from_station",
        "epidemiological_week",
        select(
            func.count(),
            func.min(ClimateObservation.week_start),
            func.max(ClimateObservation.week_start),
        ).where(column.is_not(None)),
        semantics=(
            f"Filas con {metric}; la procedencia por métrica se conserva en metric_provenance."
        ),
    )


async def stored_data_inventory(
    session: AsyncSession,
    sources: list[DataSource],
) -> list[StoredDatasetInventory]:
    measures = _measures()
    result: list[StoredDatasetInventory] = []
    for source in sources:
        measure = measures.get(source.id)
        values = (await session.execute(measure.statement)).one() if measure else (0,)
        rows = int(values[0] or 0)
        period_start, period_end = _period(values[1:], measure.period_kind if measure else "none")
        last_run = await session.scalar(
            select(IngestionRun)
            .where(
                IngestionRun.source_id == source.id,
                IngestionRun.status.in_(
                    [PipelineStatus.SUCCEEDED.value, PipelineStatus.PARTIAL.value]
                ),
            )
            .order_by(IngestionRun.finished_at.desc())
            .limit(1)
        )
        snapshot_count = int(
            await session.scalar(
                select(func.count()).select_from(RawSnapshot).where(
                    RawSnapshot.source_id == source.id
                )
            )
            or 0
        )
        snapshot = None
        if last_run is not None:
            snapshot = await session.scalar(
                select(RawSnapshot).where(RawSnapshot.ingestion_run_id == last_run.id)
            )
        storage_status = "canonical" if rows else "raw_only" if snapshot_count else "empty"
        result.append(
            StoredDatasetInventory(
                source_id=source.id,
                source_name=source.name,
                catalog_status=source.status,
                sync_enabled=source.status not in {
                    SourceStatus.DISABLED.value,
                    SourceStatus.REQUIRES_CONFIGURATION.value,
                },
                canonical_table=measure.table if measure else "not_mapped",
                rows=rows,
                has_stored_data=bool(rows or snapshot_count),
                storage_status=storage_status,
                raw_snapshot_count=snapshot_count,
                territorial_resolution=measure.territory if measure else "not_applicable",
                temporal_resolution=measure.temporal if measure else "not_applicable",
                period_start=period_start,
                period_end=period_end,
                last_ingestion_at=last_run.finished_at if last_run else None,
                last_snapshot_sha256=snapshot.sha256 if snapshot else None,
                quality_status=last_run.status if last_run else None,
                rows_rejected_last_run=last_run.rows_rejected if last_run else 0,
                semantics=(
                    measure.semantics
                    if measure
                    else "Fuente catalogada sin tabla canónica asignada."
                ),
            )
        )
    return result


def _period(values: tuple[Any, ...], kind: str) -> tuple[date | None, date | None]:
    if len(values) < 2 or values[0] is None or values[1] is None:
        return None, None
    if kind == "date":
        return values[0], values[1]
    if kind == "year":
        return date(int(values[0]), 1, 1), date(int(values[1]), 12, 31)
    if kind == "year_month":
        start, end = int(values[0]), int(values[1])
        return date(start // 100, start % 100, 1), date(end // 100, end % 100, 1)
    return None, None
