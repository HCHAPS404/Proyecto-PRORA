from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.cli import OperatorCommandError, create_operator
from app.core.config import Settings
from app.ingestion.snapshots import RawSnapshotWriter
from app.models.epidemiology import (
    EpidemiologicalObservation,
    IngestionRun,
    Municipality,
    PipelineStatus,
    RawSnapshot,
)
from app.schemas.sources import SourceSyncRequest
from app.services.source_sync import process_source_sync, schedule_source_sync


def test_snapshot_manifest_is_checksum_verified_and_write_once(tmp_path: Path) -> None:
    writer = RawSnapshotWriter(
        root=tmp_path,
        source_id="official-source",
        run_id="4dcdebed-138f-4ab7-b2cc-754699c94418",
        source_url="https://example.gov/data",
        dataset_id="abcd-1234",
        query={"year": 2022},
    )
    writer.append_page([{"code": "05001", "cases": 2}])
    writer.append_page([{"code": "05002", "cases": 3}])
    artifact = writer.finalize()

    content = Path(artifact.object_path).read_bytes()
    assert sha256(content).hexdigest() == artifact.sha256
    assert artifact.manifest["row_count"] == 2
    assert artifact.manifest["page_count"] == 2
    assert artifact.manifest["query"] == {"year": 2022}
    with pytest.raises(FileExistsError):
        RawSnapshotWriter(
            root=tmp_path,
            source_id="official-source",
            run_id="4dcdebed-138f-4ab7-b2cc-754699c94418",
            source_url="https://example.gov/data",
            dataset_id="abcd-1234",
            query={},
        )


def test_inventory_distinguishes_catalog_from_canonical_storage(client: TestClient) -> None:
    async def seed() -> str:
        factory = client.app.state.session_factory
        async with factory() as session:
            municipality = Municipality(
                code="76001",
                name="Cali",
                department_code="76",
                department_name="Valle del Cauca",
            )
            run = IngestionRun(
                source_id="sivigila-national",
                status=PipelineStatus.SUCCEEDED.value,
                finished_at=datetime.now(UTC),
                rows_read=1,
                rows_accepted=1,
                checksum="a" * 64,
                provenance={"kind": "official_source_sync", "snapshot_path": "private"},
            )
            session.add_all([municipality, run])
            await session.flush()
            session.add(
                EpidemiologicalObservation(
                    municipality_code="76001",
                    disease="dengue",
                    week_start=date(2022, 12, 25),
                    epidemiological_week=52,
                    epidemiological_year=2022,
                    cases=4,
                    source_id="sivigila-national",
                    ingestion_run_id=run.id,
                )
            )
            session.add(
                RawSnapshot(
                    ingestion_run_id=run.id,
                    source_id="sivigila-national",
                    object_path="/private/records.ndjson",
                    manifest_path="/private/manifest.json",
                    content_bytes=10,
                    row_count=1,
                    page_count=1,
                    sha256="a" * 64,
                    schema_sha256="b" * 64,
                    manifest={"query": {"year": 2022}},
                    retrieved_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return run.id

    run_id = asyncio.run(seed())
    response = client.get("/api/v1/sources/inventory")
    assert response.status_code == 200
    by_id = {item["source_id"]: item for item in response.json()}
    assert by_id["sivigila-national"]["storage_status"] == "canonical"
    assert by_id["sivigila-national"]["rows"] == 1
    assert by_id["ideam-precipitation"]["storage_status"] == "empty"
    assert by_id["ideam-precipitation"]["catalog_status"] == "active"

    manifest = client.get(f"/api/v1/sources/runs/{run_id}/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["manifest"]["query"] == {"year": 2022}
    assert "/private/" not in manifest.text


def test_operator_cli_is_explicit_and_idempotent(settings: Settings) -> None:
    async def exercise() -> None:
        created = await create_operator(
            settings,
            email="operator@example.org",
            role="analyst",
            full_name="Operador PRORA",
            password="SecureOperator123!",
        )
        assert created["status"] == "created"
        unchanged = await create_operator(
            settings,
            email="operator@example.org",
            role="analyst",
        )
        assert unchanged["status"] == "unchanged"
        with pytest.raises(OperatorCommandError):
            await create_operator(settings, email="operator@example.org", role="admin")
        promoted = await create_operator(
            settings,
            email="operator@example.org",
            role="admin",
            promote_existing=True,
        )
        assert promoted["status"] == "promoted"

    asyncio.run(exercise())


def test_sivigila_sync_is_snapshotted_aggregated_and_idempotent(
    client: TestClient,
    tmp_path: Path,
) -> None:
    client.app.state.settings.raw_snapshot_dir = str(tmp_path / "raw")
    rows = [
        {
            ":id": "1",
            "cod_eve": "210",
            "nombre_evento": "Dengue",
            "semana": "1",
            "ano": "2018",
            "cod_dpto_o": "76",
            "cod_mun_o": "1",
            "departamento_ocurrencia": "Valle del Cauca",
            "municipio_ocurrencia": "Cali",
            "conteo": "3",
        },
        {
            ":id": "2",
            "cod_eve": "220",
            "nombre_evento": "Dengue grave",
            "semana": "1",
            "ano": "2018",
            "cod_dpto_o": "76",
            "cod_mun_o": "1",
            "departamento_ocurrencia": "Valle del Cauca",
            "municipio_ocurrencia": "Cali",
            "conteo": "2",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/views/4hyg-wa9d":
            return httpx.Response(
                200,
                json={
                    "id": "4hyg-wa9d",
                    "name": "SIVIGILA agregado",
                    "owner": {"displayName": "INS"},
                },
                request=request,
            )
        assert request.url.path == "/resource/4hyg-wa9d.json"
        return httpx.Response(200, json=rows, request=request)

    async def exercise() -> tuple[int, int, int, str]:
        factory = client.app.state.session_factory
        transport = httpx.MockTransport(handler)
        async with factory() as session:
            session.add(
                Municipality(
                    code="76001",
                    name="Cali",
                    department_code="76",
                    department_name="Valle del Cauca",
                )
            )
            await session.commit()
        async with httpx.AsyncClient(transport=transport) as http_client:
            for _ in range(2):
                async with factory() as session:
                    run = await schedule_source_sync(
                        session,
                        "sivigila-national",
                        SourceSyncRequest(
                            mode="backfill",
                            from_date=date(2018, 1, 1),
                            to_date=date(2019, 1, 1),
                        ),
                    )
                    completed = await process_source_sync(
                        session,
                        run,
                        client.app.state.settings,
                        http_client=http_client,
                    )
                    assert completed.status == PipelineStatus.SUCCEEDED.value
        async with factory() as session:
            observation = await session.scalar(select(EpidemiologicalObservation))
            observation_count = int(
                await session.scalar(
                    select(func.count()).select_from(EpidemiologicalObservation)
                )
                or 0
            )
            snapshot_count = int(
                await session.scalar(select(func.count()).select_from(RawSnapshot)) or 0
            )
            latest = await session.scalar(
                select(RawSnapshot).order_by(RawSnapshot.retrieved_at.desc())
            )
            assert observation is not None and latest is not None
            return observation.cases, observation_count, snapshot_count, latest.sha256

    cases, observation_count, snapshot_count, snapshot_sha256 = asyncio.run(exercise())
    assert cases == 5
    assert observation_count == 1
    assert snapshot_count == 2
    assert len(snapshot_sha256) == 64
