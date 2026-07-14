from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.jobs.ingestion import claim_ingestion_job, process_ingestion_job
from app.models.epidemiology import (
    EpidemiologicalObservation,
    IngestionRun,
    Municipality,
    PipelineStatus,
)


def test_canonical_epidemiology_upload_is_persisted(
    client: TestClient, tmp_path: Path
) -> None:
    upload = tmp_path / "epidemiology.csv"
    upload.write_text(
        "municipality_code,disease,week_start,cases,population,is_preliminary,quality_score\n"
        "76001,dengue,2026-07-06,14,2200000,true,0.98\n",
        encoding="utf-8",
    )
    content = upload.read_bytes()
    client.app.state.settings.raw_snapshot_dir = str(tmp_path / "raw")

    async def run_job() -> tuple[str, int, int]:
        factory = client.app.state.session_factory
        async with factory() as session:
            session.add(
                Municipality(
                    code="76001",
                    name="Cali",
                    department_code="76",
                    department_name="Valle del Cauca",
                )
            )
            ingestion = IngestionRun(
                source_id="sivigila-current-authorized",
                status=PipelineStatus.PENDING.value,
                checksum=sha256(content).hexdigest(),
                provenance={
                    "dataset_type": "epidemiology",
                    "upload_path": str(upload),
                    "original_filename": upload.name,
                    "content_bytes": len(content),
                },
            )
            session.add(ingestion)
            await session.commit()

        async with factory() as session:
            claimed = await claim_ingestion_job(session)
            assert claimed is not None
            await process_ingestion_job(session, claimed, client.app.state.settings)

        async with factory() as session:
            stored_run = await session.get(IngestionRun, ingestion.id)
            observation = await session.scalar(
                select(EpidemiologicalObservation).where(
                    EpidemiologicalObservation.municipality_code == "76001"
                )
            )
            assert stored_run is not None
            assert observation is not None
            return stored_run.status, stored_run.rows_accepted, observation.cases

    status, accepted, cases = asyncio.run(run_job())
    assert status == PipelineStatus.SUCCEEDED.value
    assert accepted == 1
    assert cases == 14


def test_upload_template_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/sources/templates/epidemiology")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.startswith("municipality_code,disease,week_start,cases")
