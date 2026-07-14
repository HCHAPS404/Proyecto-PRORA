"""Source-row to canonical-contract normalization functions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .contracts import (
    ClimateObservation,
    DeforestationObservation,
    EpidemiologicalObservation,
    SocioeconomicObservation,
    VaccinationObservation,
)
from .divipola import territory
from .provenance import build_provenance
from .quality import (
    QualityIssue,
    QualityReport,
    Severity,
    nonnegative_issue,
    range_issue,
    report,
)


class RowNormalizationError(ValueError):
    pass


def normalize_sivigila(
    row: Mapping[str, Any], *, dataset_id: str = "4hyg-wa9d"
) -> tuple[EpidemiologicalObservation, QualityReport]:
    try:
        year = int(float(row["ano"]))
        week = int(float(row["semana"]))
        cases = int(float(row["conteo"]))
        event_code = str(row["cod_eve"]).split(".", 1)[0]
        event_name = str(row["nombre_evento"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise RowNormalizationError(f"Invalid SIVIGILA row: {exc}") from exc
    quality = report(
        range_issue("epidemiological_week", week, 1, 53),
        nonnegative_issue("cases", cases),
    )
    provenance = build_provenance(
        row,
        source_system="INS SIVIGILA",
        dataset_id=dataset_id,
        attribution="Instituto Nacional de Salud - INS",
    )
    item = EpidemiologicalObservation(
        event_code=event_code,
        event_name=event_name,
        epidemiological_year=year,
        epidemiological_week=week,
        cases=cases,
        territory=territory(
            department_code=row.get("cod_dpto_o"),
            municipality_code=row.get("cod_mun_o"),
            department_name=_optional_text(row.get("departamento_ocurrencia")),
            municipality_name=_optional_text(row.get("municipio_ocurrencia")),
        ),
        provenance=provenance,
        quality_flags=quality.flags,
    )
    return item, quality


def normalize_pai(
    row: Mapping[str, Any], *, dataset_id: str = "6i25-2hdt"
) -> tuple[VaccinationObservation, QualityReport]:
    try:
        year = int(float(row["a_o"]))
        coverage = float(row["cobertura_de_vacunaci_n"])
        biologic = str(row["biol_gico"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise RowNormalizationError(f"Invalid PAI row: {exc}") from exc
    quality = report(
        range_issue("coverage_percent", coverage, 0, 150),
        QualityIssue(
            "administrative_coverage_above_100",
            "Cobertura administrativa mayor a 100%; revisar denominador poblacional",
            "coverage_percent",
            Severity.WARNING,
        )
        if 100 < coverage <= 150
        else None,
    )
    provenance = build_provenance(
        row,
        source_system="MinSalud PAI",
        dataset_id=dataset_id,
        attribution="Ministerio de Salud y Protección Social",
    )
    item = VaccinationObservation(
        year=year,
        biologic=biologic,
        coverage_percent=coverage,
        territory=territory(
            department_code=row.get("coddepto"),
            department_name=_optional_text(row.get("departamento")),
        ),
        provenance=provenance,
        quality_flags=quality.flags,
    )
    return item, quality


def normalize_ideam_climate(
    row: Mapping[str, Any], *, dataset_id: str = "57sv-p2fu"
) -> tuple[ClimateObservation, QualityReport]:
    try:
        timestamp = str(row["fechaobservacion"]).replace("Z", "+00:00")
        observed_at = datetime.fromisoformat(timestamp)
        value = float(row["valorobservado"])
        station_code = str(row["codigoestacion"])
        sensor_code = str(row["codigosensor"])
        metric = str(row["descripcionsensor"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise RowNormalizationError(f"Invalid IDEAM climate row: {exc}") from exc
    latitude = _optional_float(row.get("latitud"))
    longitude = _optional_float(row.get("longitud"))
    quality = report(
        range_issue("latitude", latitude, -4.5, 13.7) if latitude is not None else None,
        range_issue("longitude", longitude, -82.0, -66.5) if longitude is not None else None,
    )
    provenance = build_provenance(
        row,
        source_system="IDEAM estaciones hidrometeorológicas",
        dataset_id=dataset_id,
        attribution="Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM",
        license_name="Creative Commons Attribution ShareAlike 4.0",
    )
    item = ClimateObservation(
        observed_at=observed_at,
        station_code=station_code,
        sensor_code=sensor_code,
        metric=metric,
        value=value,
        unit=_optional_text(row.get("unidadmedida")),
        territory=territory(
            department_name=_optional_text(row.get("departamento")),
            municipality_name=_optional_text(row.get("municipio")),
        ),
        latitude=latitude,
        longitude=longitude,
        provider=_optional_text(row.get("entidad")),
        provenance=provenance,
        quality_flags=quality.flags,
    )
    return item, quality


def normalize_deforestation(
    row: Mapping[str, Any],
    *,
    dataset_id: str,
    field_map: Mapping[str, str],
) -> tuple[DeforestationObservation, QualityReport]:
    """Normalize a configured tabular IDEAM publication without assuming an unstable schema."""
    _require_mapping(field_map, "year", "hectares")
    try:
        year = int(float(row[field_map["year"]]))
        hectares = float(row[field_map["hectares"]])
    except (KeyError, TypeError, ValueError) as exc:
        raise RowNormalizationError(f"Invalid IDEAM deforestation row: {exc}") from exc
    quality = report(nonnegative_issue("hectares", hectares))
    provenance = build_provenance(
        row,
        source_system="IDEAM deforestación",
        dataset_id=dataset_id,
        attribution="Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM",
    )
    item = DeforestationObservation(
        year=year,
        hectares=hectares,
        territory=_mapped_territory(row, field_map),
        provenance=provenance,
        quality_flags=quality.flags,
    )
    return item, quality


def normalize_dane_socioeconomic(
    row: Mapping[str, Any],
    *,
    dataset_id: str,
    field_map: Mapping[str, str],
) -> tuple[SocioeconomicObservation, QualityReport]:
    """Normalize a deliberately selected DANE table using an explicit field contract."""
    _require_mapping(field_map, "year", "indicator", "value", "unit")
    try:
        year = int(float(row[field_map["year"]]))
        indicator = str(row[field_map["indicator"]]).strip()
        value = float(row[field_map["value"]])
        unit = str(row[field_map["unit"]]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise RowNormalizationError(f"Invalid DANE socioeconomic row: {exc}") from exc
    quality = QualityReport()
    provenance = build_provenance(
        row,
        source_system="DANE socioeconómico",
        dataset_id=dataset_id,
        attribution="Departamento Administrativo Nacional de Estadística - DANE",
    )
    dimensions = {
        canonical: row[source]
        for canonical, source in field_map.items()
        if canonical.startswith("dimension.") and source in row
    }
    item = SocioeconomicObservation(
        year=year,
        indicator=indicator,
        value=value,
        unit=unit,
        territory=_mapped_territory(row, field_map),
        dimensions=dimensions,
        provenance=provenance,
    )
    return item, quality


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _require_mapping(field_map: Mapping[str, str], *required: str) -> None:
    missing = [name for name in required if not field_map.get(name)]
    if missing:
        raise RowNormalizationError(f"Missing canonical field mapping: {', '.join(missing)}")


def _mapped_territory(row: Mapping[str, Any], field_map: Mapping[str, str]):
    def mapped(name: str) -> Any:
        source = field_map.get(name)
        return row.get(source) if source else None

    return territory(
        department_code=mapped("department_code"),
        municipality_code=mapped("municipality_code"),
        department_name=_optional_text(mapped("department_name")),
        municipality_name=_optional_text(mapped("municipality_name")),
    )
