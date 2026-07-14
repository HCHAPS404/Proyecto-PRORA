from __future__ import annotations

from openpyxl import Workbook

from app.ingestion.pai_files import (
    PAI_2026_CONTRACT,
    ParsedPAIFile,
    _parse_sheet,
)


def test_current_pai_uses_divipola_code_and_traces_legacy_name_aliases() -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Enero"
    worksheet.cell(6, 6, "% DE TV AL AÑO DE EDAD")

    official: dict[str, str] = {}
    for offset in range(1, 1123):
        department = 1 if offset <= 999 else 2
        local_code = offset if offset <= 999 else offset - 999
        code = f"{department:02d}{local_code:03d}"
        official_name = f"Municipio oficial {offset}"
        source_name = "Nombre histórico abreviado" if offset == 1 else official_name
        official[code] = official_name
        worksheet.append([department, None, code, source_name, 100, 95.0])

    result = ParsedPAIFile(schema_descriptor={"adapter_version": "test"})
    _parse_sheet(
        worksheet,
        sheet_name="Enero",
        year=2026,
        month=1,
        header_row=6,
        measures={"triple_viral_1y": 5},
        result=result,
        contract=PAI_2026_CONTRACT,
        official_municipalities=official,
    )

    assert len(result.records) == 1122
    assert not any(
        rejection.reason_code == "territory_cardinality_mismatch"
        for rejection in result.rejections
    )
    assert result.schema_descriptor["territory_name_aliases"] == [
        {
            "sheet": "Enero",
            "municipality_code": "01001",
            "source_name": "Nombre histórico abreviado",
            "divipola_name": "Municipio oficial 1",
        }
    ]
