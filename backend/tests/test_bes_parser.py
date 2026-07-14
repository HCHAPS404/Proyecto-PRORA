from __future__ import annotations

from app.ingestion import bes


class _Page:
    def __init__(self, table: list[list[object]]) -> None:
        self._table = table

    def extract_text(self) -> str:
        headings = " ".join(str(value or "") for value in self._table[0])
        return (
            "Comportamiento de la notificacion por entidad territorial a semana "
            f"epidemiologica 26 {headings}\n28 de junio al 04 de julio de 2026"
        )

    def extract_tables(self) -> list[list[list[object]]]:
        return [self._table]


class _Document:
    def __init__(self, pages: list[_Page]) -> None:
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_bes_parser_preserves_published_resolution_and_metric_semantics(monkeypatch) -> None:
    dengue = [
        ["", "Dengue General (Dengue y Dengue Grave)", None, None],
        ["Tipo", "Casos probables", None, None],
        ["Departamento", "Acumulado 2026", "Esperado", "Observado"],
        ["Santiago de Cali D.E.", "12", "3", "4"],
        ["Total nacional", "30", "5", "7"],
    ]
    malaria_ira = [
        ["", "Malaria", None, None, "Morbilidad por IRA consulta externa y urgencias", None, None],
        ["Tipo", "Confirmados", None, None, "Notificacion colectiva", None, None],
        [
            "Departamento",
            "Acumulado 2026",
            "Esperado",
            "Observado",
            "Acumulado 2026",
            "Esperado",
            "Observado",
        ],
        ["Antioquia", "20", "4", "6", "200", "40", "60"],
        ["Total nacional", "40", "8", "12", "400", "80", "120"],
    ]
    cumulative = [
        ["", "Chikungunña", None, "Enfermedad por virus Zika", None, "Leishmaniasis Cutanea", None],
        ["Tipo", "Confirmados", None, "Confirmados", None, "Confirmados", None],
        [
            "Departamento",
            "Acumulado esperado",
            "Acumulado 2026",
            "Acumulado esperado",
            "Acumulado 2026",
            "Acumulado esperado",
            "Acumulado 2026",
        ],
        ["Antioquia", "1", "2", "3", "4", "5", "6"],
        ["Total nacional", "7", "8", "9", "10", "11", "12"],
    ]
    monkeypatch.setattr(
        bes.pdfplumber,
        "open",
        lambda _: _Document([_Page(dengue), _Page(malaria_ira), _Page(cumulative)]),
    )

    parsed = bes.parse_bes_publication("ignored.pdf")

    assert parsed.contract_valid is True
    assert parsed.epidemiological_week == 26
    assert parsed.period_end.isoformat() == "2026-07-04"
    assert parsed.diseases_found == [
        "chikunguna",
        "dengue",
        "ira",
        "leishmaniasis",
        "malaria",
        "zika",
    ]
    cali = next(
        item
        for item in parsed.records
        if item.disease == "dengue" and item.territory_code == "76001"
    )
    assert cali.territory_level == "district"
    assert cali.cumulative_cases == 12
    assert cali.observed_cases == 4
    national_zika = next(
        item
        for item in parsed.records
        if item.disease == "zika" and item.territory_code == "national"
    )
    assert national_zika.cumulative_cases == 10
    assert national_zika.expected_cases == 9
    assert national_zika.observed_cases is None
    assert national_zika.comparison_basis == "cumulative_expected_observed"
