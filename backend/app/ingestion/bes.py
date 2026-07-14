"""Versioned parser for INS Boletin Epidemiologico Semanal (BES) tables.

The bulletin is an official PDF, not a stable tabular API.  This adapter keeps
the current reference layer separate from municipal SIVIGILA observations and
fails closed when the expected table contract changes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pdfplumber

BES_ADAPTER_VERSION = "ins-bes-v1.0"

MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

DEPARTMENT_CODES = {
    "amazonas": "91",
    "antioquia": "05",
    "arauca": "81",
    "atlantico": "08",
    "bolivar": "13",
    "boyaca": "15",
    "caldas": "17",
    "caqueta": "18",
    "casanare": "85",
    "cauca": "19",
    "cesar": "20",
    "choco": "27",
    "cordoba": "23",
    "cundinamarca": "25",
    "guainia": "94",
    "guaviare": "95",
    "huila": "41",
    "la guajira": "44",
    "magdalena": "47",
    "meta": "50",
    "narino": "52",
    "norte de santander": "54",
    "putumayo": "86",
    "quindio": "63",
    "risaralda": "66",
    "archipielago de san andres y providencia": "88",
    "santander": "68",
    "sucre": "70",
    "tolima": "73",
    "valle del cauca": "76",
    "vaupes": "97",
    "vichada": "99",
}

DISTRICT_CODES = {
    "barranquilla d e": "08001",
    "bogota d c": "11001",
    "buenaventura d e": "76109",
    "santiago de cali d e": "76001",
    "cartagena de indias d t": "13001",
    "santa marta d t": "47001",
}


@dataclass(frozen=True, slots=True)
class BESRecord:
    territory_code: str
    territory_name: str
    territory_level: str
    disease: str
    event_label: str
    epidemiological_year: int
    epidemiological_week: int
    period_start: date
    period_end: date
    cumulative_cases: int
    expected_cases: int | None
    observed_cases: int | None
    comparison_basis: str
    source_page: int


@dataclass(frozen=True, slots=True)
class BESParseResult:
    records: list[BESRecord]
    epidemiological_year: int
    epidemiological_week: int
    period_start: date
    period_end: date
    pages_scanned: int
    diseases_found: list[str]
    schema_descriptor: dict
    contract_valid: bool


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().casefold()
    return text


def _integer(value: object) -> int:
    text = re.sub(r"[^0-9-]", "", str(value or ""))
    if not text or text == "-":
        raise ValueError(f"Valor entero BES invalido: {value!r}")
    result = int(text)
    if result < 0:
        raise ValueError(f"Conteo BES negativo: {result}")
    return result


def _territory(name: str) -> tuple[str, str]:
    normalized = _normalize(name)
    if normalized == "total nacional":
        return "national", "national"
    if normalized in DISTRICT_CODES:
        return DISTRICT_CODES[normalized], "district"
    if normalized in DEPARTMENT_CODES:
        return DEPARTMENT_CODES[normalized], "department"
    raise ValueError(f"Entidad territorial BES no reconocida: {name}")


def _period(text: str) -> tuple[int, int, date, date]:
    normalized = _normalize(text)
    week_match = re.search(r"semana epidemiologica\s+(\d{1,2})", normalized)
    date_match = re.search(
        r"(\d{1,2}) de ([a-z]+) al (\d{1,2}) de ([a-z]+) de (\d{4})",
        normalized,
    )
    if not week_match or not date_match:
        raise ValueError("No fue posible identificar semana y periodo del BES")
    week = int(week_match.group(1))
    start_day, start_month_name, end_day, end_month_name, year_text = date_match.groups()
    year = int(year_text)
    start_month = MONTHS[start_month_name]
    end_month = MONTHS[end_month_name]
    start_year = year - 1 if start_month > end_month else year
    return week, year, date(start_year, start_month, int(start_day)), date(
        year, end_month, int(end_day)
    )


def _table_specs(header: list[object]) -> list[tuple[int, str, str, int]]:
    specs: list[tuple[int, str, str, int]] = []
    for index, cell in enumerate(header):
        label = _normalize(cell)
        if not label:
            continue
        if "dengue general" in label:
            specs.append((index, "dengue", str(cell), 3))
        elif label == "malaria":
            specs.append((index, "malaria", str(cell), 3))
        elif "morbilidad por ira consulta" in label:
            specs.append((index, "ira", str(cell), 3))
        elif "chikung" in label:
            specs.append((index, "chikunguna", str(cell), 2))
        elif "virus zika" in label:
            specs.append((index, "zika", str(cell), 2))
        elif "leishmaniasis" in label:
            specs.append((index, "leishmaniasis", str(cell), 2))
    return specs


def parse_bes_publication(path: str | Path) -> BESParseResult:
    records: list[BESRecord] = []
    pages_scanned = 0
    period_data: tuple[int, int, date, date] | None = None
    with pdfplumber.open(Path(path)) as document:
        pages_scanned = len(document.pages)
        for page_number, page in enumerate(document.pages, start=1):
            page_text = page.extract_text() or ""
            normalized_page = _normalize(page_text)
            table_markers = (
                "dengue",
                "morbilidad por ira",
                "chikung",
                "virus zika",
                "leishmaniasis",
            )
            if "malaria" not in normalized_page and not any(
                marker in normalized_page for marker in table_markers
            ):
                continue
            for table in page.extract_tables():
                if len(table) < 4 or not table[0]:
                    continue
                specs = _table_specs(table[0])
                if not specs:
                    continue
                if period_data is None:
                    period_data = _period(page_text)
                week, year, period_start, period_end = period_data
                for row in table[3:]:
                    territory_name = str(row[0] or "").strip()
                    if not territory_name:
                        continue
                    territory_code, territory_level = _territory(territory_name)
                    for index, disease, event_label, width in specs:
                        if index + width - 1 >= len(row):
                            raise ValueError("La tabla BES cambio el numero de columnas esperado")
                        if width == 3:
                            cumulative = _integer(row[index])
                            expected = _integer(row[index + 1])
                            observed = _integer(row[index + 2])
                            basis = "weekly_expected_observed"
                        else:
                            expected = _integer(row[index])
                            cumulative = _integer(row[index + 1])
                            observed = None
                            basis = "cumulative_expected_observed"
                        records.append(
                            BESRecord(
                                territory_code=territory_code,
                                territory_name=territory_name,
                                territory_level=territory_level,
                                disease=disease,
                                event_label=event_label.replace("\n", " "),
                                epidemiological_year=year,
                                epidemiological_week=week,
                                period_start=period_start,
                                period_end=period_end,
                                cumulative_cases=cumulative,
                                expected_cases=expected,
                                observed_cases=observed,
                                comparison_basis=basis,
                                source_page=page_number,
                            )
                        )
    if period_data is None:
        raise ValueError("El PDF no contiene un periodo epidemiologico reconocible")
    diseases = sorted({record.disease for record in records})
    expected_diseases = {
        "dengue",
        "malaria",
        "chikunguna",
        "zika",
        "leishmaniasis",
        "ira",
    }
    contract_valid = expected_diseases.issubset(diseases) and all(
        any(record.territory_code == "national" for record in records if record.disease == disease)
        for disease in expected_diseases
    )
    week, year, period_start, period_end = period_data
    return BESParseResult(
        records=records,
        epidemiological_year=year,
        epidemiological_week=week,
        period_start=period_start,
        period_end=period_end,
        pages_scanned=pages_scanned,
        diseases_found=diseases,
        schema_descriptor={
            "adapter_version": BES_ADAPTER_VERSION,
            "territory_levels": ["national", "department", "district"],
            "diseases": diseases,
            "metrics": ["cumulative_cases", "expected_cases", "observed_cases"],
            "current_reference_is_separate_from_training_panel": True,
        },
        contract_valid=contract_valid,
    )
