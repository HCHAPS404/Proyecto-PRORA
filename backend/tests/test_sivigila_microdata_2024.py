from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from app.connectors.sivigila_microdata import (
    SIVIGILA_2024_EVENT_FILES,
    SIVIGILA_MICRODATA_DISCOVERY_URL,
    sivigila_2024_event_files,
)
from app.core.errors import DomainError
from app.ingestion.sivigila_microdata import (
    SIVIGILAMicrodataContractError,
    parse_sivigila_2024_workbook,
)
from app.models.epidemiology import (
    EpidemiologicalObservation,
    Municipality,
    PipelineStatus,
    RawSnapshot,
    SourceStatus,
)
from app.schemas.sources import SourceSyncRequest
from app.services.source_catalog import OFFICIAL_SOURCE_CATALOG
from app.services.source_sync import (
    _validate_sivigila_microdata_selection,
    process_source_sync,
    schedule_source_sync,
)


def _workbook(headers: list[str], rows: list[list[object]]) -> BytesIO:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    stream.seek(0)
    return stream


def test_case_microdata_is_aggregated_without_quasi_identifiers() -> None:
    headers = [
        "CONSECUTIVE",
        "COD_EVE",
        "SEMANA",
        "ANO",
        "COD_DPTO_O",
        "COD_MUN_O",
        "EDAD",
        "SEXO",
        "OCUPACION",
    ]
    stream = _workbook(
        headers,
        [
            ["private-row-a", 895, 14, 2024, "05", "001", 28, "F", "secret-a"],
            ["private-row-b", 895, 14, 2024, "05", "001", 61, "M", "secret-b"],
            ["private-row-c", 895, 15, 2024, "76", "001", 42, "F", "secret-c"],
        ],
    )

    parsed = parse_sivigila_2024_workbook(stream, SIVIGILA_2024_EVENT_FILES[895])

    assert parsed.rows_seen == 3
    assert parsed.rows_accepted == 3
    assert [(record.municipality_code, record.value) for record in parsed.records] == [
        ("05001", 2),
        ("76001", 1),
    ]
    disclosed = repr([record.snapshot_payload() for record in parsed.records])
    assert "private-row" not in disclosed
    assert "secret-" not in disclosed
    assert "EDAD" not in disclosed
    assert parsed.schema_descriptor["raw_rows_persisted"] is False
    assert parsed.schema_descriptor["quasi_identifiers_persisted"] is False
    assert set(parsed.schema_descriptor["persisted_columns"]) == set(
        parsed.records[0].snapshot_payload()
    )


def test_collective_ira_uses_service_totals_and_stays_context_only() -> None:
    stream = _workbook(
        [
            "num_con",
            "cod_eve",
            "semana",
            "año",
            "cod_mun",
            "tot_irag",
            "tot_irauci",
            "tot_iraext",
            "nit_upgd",
        ],
        [
            ["one", 995, 8, 2024, "11001", 3, 2, 11, "not-persisted"],
            ["two", 995, 8, 2024, "11001", 1, 0, 5, "not-persisted"],
        ],
    )

    parsed = parse_sivigila_2024_workbook(stream, SIVIGILA_2024_EVENT_FILES[995])

    assert len(parsed.records) == 1
    record = parsed.records[0]
    assert record.value == 22
    assert record.measure == "ira_morbidity_attendances"
    assert record.canonical_eligible is False
    assert record.territorial_semantics == "notifying_municipality"
    assert "nit_upgd" not in repr(record.snapshot_payload()).lower()


def test_duplicate_source_identity_is_rejected_with_safe_payload_only() -> None:
    stream = _workbook(
        ["CONSECUTIVE", "COD_EVE", "SEMANA", "ANO", "COD_DPTO_O", "COD_MUN_O"],
        [
            ["same-private-id", 217, 2, 2024, "08", "001"],
            ["same-private-id", 217, 2, 2024, "08", "001"],
        ],
    )

    parsed = parse_sivigila_2024_workbook(stream, SIVIGILA_2024_EVENT_FILES[217])

    assert parsed.rows_accepted == 1
    assert parsed.rows_rejected == 1
    assert parsed.duplicate_rows == 1
    assert "same-private-id" not in repr(parsed.rejections)
    assert parsed.rejections[0].safe_payload == {
        "event_code": 217,
        "epidemiological_year": 2024,
        "epidemiological_week": 2,
        "municipality_code": "08001",
    }


def test_contract_rejects_missing_municipality_column() -> None:
    stream = _workbook(
        ["CONSECUTIVE", "COD_EVE", "SEMANA", "ANO", "COD_DPTO_O"],
        [["row", 210, 1, 2024, "05"]],
    )
    with pytest.raises(SIVIGILAMicrodataContractError, match="COD_MUN_O"):
        parse_sivigila_2024_workbook(stream, SIVIGILA_2024_EVENT_FILES[210])


def test_catalog_has_verified_files_and_requires_complete_disease_groups() -> None:
    assert SIVIGILA_MICRODATA_DISCOVERY_URL.startswith("https://")
    assert len(sivigila_2024_event_files()) == 14
    assert all(contract.url.startswith("https://") for contract in sivigila_2024_event_files())
    assert [item.event_code for item in sivigila_2024_event_files([895])] == [895]
    with pytest.raises(DomainError) as error:
        _validate_sivigila_microdata_selection([210])
    assert error.value.code == "incomplete_event_group"
    assert {item.event_code for item in _validate_sivigila_microdata_selection([210, 220])} == {
        210,
        220,
    }
    source = next(
        item for item in OFFICIAL_SOURCE_CATALOG if item["id"] == "sivigila-microdata-2024"
    )
    assert source["status"] == SourceStatus.ACTIVE.value
    assert source["configuration"]["raw_workbook_persistence"] is False
    assert source["configuration"]["data_through_year"] == 2024


def test_sync_persists_only_sanitised_aggregate_snapshot(
    client: TestClient, tmp_path: Path
) -> None:
    client.app.state.settings.raw_snapshot_dir = str(tmp_path / "raw")
    source_file = _workbook(
        [
            "CONSECUTIVE",
            "COD_EVE",
            "SEMANA",
            "ANO",
            "COD_DPTO_O",
            "COD_MUN_O",
            "EDAD",
            "SEXO",
        ],
        [
            ["private-one", 895, 14, 2024, "05", "001", 18, "F"],
            ["private-two", 895, 14, 2024, "05", "001", 73, "M"],
        ],
    ).getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/Microdatos/Datos_2024_895.xlsx"
        return httpx.Response(
            200,
            content=source_file,
            headers={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                "content-length": str(len(source_file)),
                "last-modified": "Sat, 13 Sep 2025 02:34:48 GMT",
            },
            request=request,
        )

    async def exercise() -> tuple:
        factory = client.app.state.session_factory
        async with factory() as session:
            session.add(
                Municipality(
                    code="05001",
                    name="Medellin",
                    department_code="05",
                    department_name="Antioquia",
                )
            )
            await session.commit()
            run = await schedule_source_sync(
                session,
                "sivigila-microdata-2024",
                SourceSyncRequest(event_codes=[895]),
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
                completed = await process_source_sync(
                    session,
                    run,
                    client.app.state.settings,
                    http_client=http_client,
                )
            observation = await session.scalar(select(EpidemiologicalObservation))
            snapshot = await session.scalar(select(RawSnapshot))
            return completed, observation, snapshot

    completed, observation, snapshot = asyncio.run(exercise())
    assert completed.status == PipelineStatus.SUCCEEDED.value
    assert completed.rows_read == 1
    assert completed.rows_accepted == 1
    assert completed.quality_report["source_rows_seen"] == 2
    assert completed.quality_report["raw_workbooks_persisted"] is False
    assert observation is not None and observation.cases == 2
    assert snapshot is not None
    persisted = Path(snapshot.object_path).read_text(encoding="utf-8")
    assert "private-one" not in persisted
    assert "private-two" not in persisted
    assert "EDAD" not in persisted
    assert "municipality_code" in persisted
    assert not list((tmp_path / "raw").rglob("*.xlsx"))
    assert snapshot.manifest["privacy"]["raw_workbooks_persisted"] is False
