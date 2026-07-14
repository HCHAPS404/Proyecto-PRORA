"""Federated territorial open-data SIVIGILA adapters (datos.gov.co).

These publications are not a national municipal API for 2025+, but they extend
municipality/week coverage for specific territories with more recent years than
``4hyg-wa9d`` / microdata 2024. Case-level rows are aggregated immediately;
nominal attributes are never persisted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.connectors.sivigila import EVENT_TO_DISEASE, PRIORITIZED_EVENT_CODES
from app.ingestion.divipola import normalize_name

RowKind = Literal["aggregate", "case"]


@dataclass(frozen=True, slots=True)
class TerritorialFieldMap:
    year: str
    week: str
    event_code: str | None = None
    event_name: str | None = None
    cases: str | None = None
    department_code: str | None = None
    municipality_code: str | None = None
    department_name: str | None = None
    municipality_name: str | None = None


@dataclass(frozen=True, slots=True)
class TerritorialSourceProfile:
    source_id: str
    dataset_id: str
    name: str
    institution: str
    kind: RowKind
    fields: TerritorialFieldMap
    year_from: int
    year_to: int
    diseases: tuple[str, ...]
    endpoint: str
    notes: str
    # Optional SoQL fragment applied as additional $where (trusted constants only).
    where_extra: str | None = None
    # When the publication is single-municipality without DIVIPOLA columns.
    fixed_municipality_code: str | None = None


_DISEASE_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "dengue": ("DENGUE",),
    "chikunguna": ("CHIKUNG",),
    "zika": ("ZIKA",),
    "leishmaniasis": ("LEISHMANIASIS",),
    "malaria": ("MALARIA",),
    "ira": (
        "IRAG",
        "INFECCION RESPIRATORIA AGUDA GRAVE",
        "IRA GRAVE",
        "IRA POR VIRUS",
        "ESI - IRAG",
    ),
}


def _strip_accents(value: str) -> str:
    return normalize_name(value).upper()


def disease_from_event_and_name(
    event_code: int | None,
    event_name: str | None,
    *,
    allowed: tuple[str, ...],
) -> str | None:
    """Resolve disease with event code + name guard (Boyacá reuses codes)."""

    name = _strip_accents(event_name or "")
    by_code = EVENT_TO_DISEASE.get(event_code) if event_code is not None else None
    if by_code in allowed:
        hints = _DISEASE_NAME_HINTS.get(by_code, ())
        if not name or any(hint in name for hint in hints):
            return by_code
    for disease in allowed:
        hints = _DISEASE_NAME_HINTS.get(disease, ())
        if any(hint in name for hint in hints):
            return disease
    return None


def pad_divipola(department_code: str | None, municipality_code: str | None) -> str | None:
    if not department_code or not municipality_code:
        return None
    dept = re.sub(r"\D", "", str(department_code))
    muni = re.sub(r"\D", "", str(municipality_code))
    if not dept or not muni:
        return None
    if len(muni) >= 5:
        return muni.zfill(5)[-5:]
    return f"{int(dept):02d}{int(muni):03d}"


TERRITORIAL_SIVIGILA_PROFILES: tuple[TerritorialSourceProfile, ...] = (
    TerritorialSourceProfile(
        source_id="sivigila-boyaca-events",
        dataset_id="tz38-fg9k",
        name="SIVIGILA eventos notificados — Boyacá",
        institution="Gobernación de Boyacá / SIVIGILA",
        kind="aggregate",
        fields=TerritorialFieldMap(
            year="ano",
            week="semana",
            event_code="cod_eve",
            event_name="nombre",
            cases="conteo_casos",
            department_code="cod_dpto",
            municipality_code="cod_mun",
            municipality_name="nom_mum",
        ),
        year_from=2019,
        year_to=2023,
        diseases=("dengue", "chikunguna", "leishmaniasis", "ira", "malaria", "zika"),
        endpoint="https://www.datos.gov.co/resource/tz38-fg9k.json",
        notes="Agregado municipio/semana/evento. Filtra por nombre para evitar códigos reutilizados.",
    ),
    TerritorialSourceProfile(
        source_id="sivigila-caqueta-dengue",
        dataset_id="fhz2-4x64",
        name="Casos de Dengue — Departamento del Caquetá",
        institution="Gobernación del Caquetá",
        kind="case",
        fields=TerritorialFieldMap(
            year="a_o_reporte",
            week="semana_epidemiol_gica",
            event_code="codigo_evento",
            event_name="nombre_del_evento",
            department_name="departamento_reporte",
            municipality_name="municipio_reporte",
        ),
        year_from=2018,
        year_to=2023,
        diseases=("dengue",),
        endpoint="https://www.datos.gov.co/resource/fhz2-4x64.json",
        notes="Filas individuales; se agregan a municipio/semana. Ver datos.gov.co/qwsm-wq4w (vista).",
    ),
    TerritorialSourceProfile(
        source_id="sivigila-pereira-dengue",
        dataset_id="tm62-e28n",
        name="Casos de dengue — ciudad de Pereira",
        institution="Alcaldía de Pereira / Risaralda",
        kind="case",
        fields=TerritorialFieldMap(
            year="ano",
            week="semana",
            event_code="codigo_del_evento",
            event_name="nombre_del_evento",
            department_name="departamento_de_ocurrencia",
            municipality_name="municipio_de_ocurrencia",
        ),
        year_from=2017,
        year_to=2024,
        diseases=("dengue",),
        endpoint="https://www.datos.gov.co/resource/tm62-e28n.json",
        notes=(
            "Serie municipal Pereira; normaliza años tipo 2.023→2023 y rechaza "
            "valores inválidos (p. ej. 2.02)."
        ),
    ),
    TerritorialSourceProfile(
        source_id="sivigila-tulua-dengue",
        dataset_id="dq2k-gub9",
        name="Casos de Dengue — Municipio de Tuluá",
        institution="Alcaldía de Tuluá / Valle del Cauca",
        kind="case",
        fields=TerritorialFieldMap(
            year="a_o",
            week="semana",
            event_code="cod_eve",
            department_code="cod_dpto_r",
            municipality_code="cod_mun_r",
            municipality_name="nmun_resi",
        ),
        year_from=2022,
        year_to=2024,
        diseases=("dengue",),
        endpoint="https://www.datos.gov.co/resource/dq2k-gub9.json",
        notes="Microdatos locales agregados de inmediato; sin persistir filas nominales.",
    ),
    TerritorialSourceProfile(
        source_id="sivigila-bucaramanga-dengue",
        dataset_id="qzc7-jbg3",
        name="Dengue / dengue grave — Municipio de Bucaramanga",
        institution="Alcaldía de Bucaramanga",
        kind="case",
        fields=TerritorialFieldMap(
            year="a_o",
            week="semana",
            event_code="cod_eve",
            event_name="nom_eve",
            department_code="cod_dpto_r",
            municipality_code="cod_mun_r",
        ),
        year_from=2015,
        year_to=2025,
        diseases=("dengue",),
        endpoint="https://www.datos.gov.co/resource/qzc7-jbg3.json",
        notes="Incluye 2025 (verificado). Extiende la serie más allá del microdato nacional 2024.",
    ),
    TerritorialSourceProfile(
        source_id="sivigila-casanare-dengue",
        dataset_id="3kuf-t86h",
        name="Casos de Dengue — Casanare",
        institution="Gobernación de Casanare",
        kind="case",
        fields=TerritorialFieldMap(
            year="a_o",
            week="semana",
            event_name="nom_eve",
            department_code="cod_dpto_o",
            municipality_code="cod_mun_o",
            department_name="ndep_resi",
            municipality_name="nmun_resi",
        ),
        year_from=2018,
        year_to=2023,
        diseases=("dengue",),
        endpoint="https://www.datos.gov.co/resource/3kuf-t86h.json",
        notes="Hospitalario/territorial; se agrega a municipio/semana con códigos DIVIPOLA.",
    ),
    TerritorialSourceProfile(
        source_id="sivigila-bucaramanga-events",
        dataset_id="map9-mdzc",
        name="Eventos de interés en salud pública — Bucaramanga",
        institution="Alcaldía de Bucaramanga",
        kind="case",
        fields=TerritorialFieldMap(
            year="ano",
            week="semana",
            event_code="cod_eve",
            event_name="nom_eve",
            department_code="cod_dpto_o",
            municipality_code="cod_mun_o",
            municipality_name="nmun_proce",
        ),
        year_from=2015,
        year_to=2025,
        diseases=("dengue", "chikunguna", "zika", "malaria", "leishmaniasis", "ira"),
        endpoint="https://www.datos.gov.co/resource/map9-mdzc.json",
        notes=(
            "Multi-evento municipal con cobertura hasta 2025 (dengue, zika, chikunguña, "
            "IRAG, malaria, leishmaniasis). Complementa el dataset solo-dengue qzc7-jbg3."
        ),
    ),
    TerritorialSourceProfile(
        source_id="sivigila-bucaramanga-ira",
        dataset_id="dtct-ww7w",
        name="Datos colectivos IRA/IRAG — Bucaramanga",
        institution="Alcaldía de Bucaramanga",
        kind="aggregate",
        fields=TerritorialFieldMap(
            year="ano",
            week="semana_epidemiologica",
            cases="total_de_eventos_de_morbilidad",
        ),
        year_from=2015,
        year_to=2025,
        diseases=("ira",),
        endpoint="https://www.datos.gov.co/resource/dtct-ww7w.json",
        notes=(
            "Agregado colectivo por UPGD/semana; se suma a municipio 68001. "
            "Extiende la serie IRA local hasta 2025."
        ),
        fixed_municipality_code="68001",
    ),
    TerritorialSourceProfile(
        source_id="sivigila-santa-rosa-cabal-events",
        dataset_id="xc7d-5tmm",
        name="Casos epidemiológicos — Santa Rosa de Cabal",
        institution="Alcaldía de Santa Rosa de Cabal",
        kind="case",
        fields=TerritorialFieldMap(
            year="a_o",
            week="semana",
            event_name="nombre_del_evento",
            department_code="codigo_departamento",
            municipality_code="codigo_municipio",
        ),
        year_from=2022,
        year_to=2024,
        diseases=("dengue", "malaria", "ira"),
        endpoint="https://www.datos.gov.co/resource/xc7d-5tmm.json",
        notes="Serie municipal 2022–2024 con dengue, malaria e IRAG/IRA.",
    ),
)


FEDERATION_SOURCE_ID = "sivigila-territorial-open"


def territorial_profiles() -> tuple[TerritorialSourceProfile, ...]:
    return TERRITORIAL_SIVIGILA_PROFILES


def profile_by_source_id(source_id: str) -> TerritorialSourceProfile | None:
    for profile in TERRITORIAL_SIVIGILA_PROFILES:
        if profile.source_id == source_id:
            return profile
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        text = str(value).strip().replace(",", "")
        if "." in text:
            text = text.split(".", 1)[0]
        number = int(text)
    except (TypeError, ValueError):
        return None
    return number


def _as_year(value: Any) -> int | None:
    """Parse epidemiological year, including locale artifacts like ``2.023`` → 2023."""

    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "")
    # Pereira and similar publications sometimes encode 2023 as "2.023".
    if re.fullmatch(r"\d\.\d{3}", text):
        try:
            return int(text.replace(".", ""))
        except ValueError:
            return None
    return _as_int(text)


def extract_year_week(row: Mapping[str, Any], fields: TerritorialFieldMap) -> tuple[int, int] | None:
    year = _as_year(row.get(fields.year))
    week = _as_int(row.get(fields.week))
    if year is None or week is None:
        return None
    if year < 2000 or year > 2100 or week < 1 or week > 53:
        return None
    return year, week


def extract_event_code(row: Mapping[str, Any], fields: TerritorialFieldMap) -> int | None:
    if not fields.event_code:
        return None
    return _as_int(row.get(fields.event_code))


def extract_cases(row: Mapping[str, Any], profile: TerritorialSourceProfile) -> int:
    if profile.kind == "case":
        return 1
    raw = row.get(profile.fields.cases or "")
    value = _as_int(raw)
    if value is None or value < 0:
        raise ValueError("invalid_case_count")
    return value
