"""Local demo helper: sync expanded open sources and retrain champions."""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.jobs.training import process_training_job
from sqlalchemy import select

from app.models.epidemiology import (
    DataSource,
    IngestionRun,
    ModelTrainingRun,
    PipelineStatus,
)
from app.schemas.sources import SourceSyncRequest
from app.services.source_catalog import seed_source_catalog
from app.services.source_sync import process_source_sync, schedule_source_sync

SYNC_SOURCES = [
    "sivigila-bucaramanga-events",
    "sivigila-bucaramanga-ira",
    "sivigila-santa-rosa-cabal-events",
    "sivigila-bucaramanga-dengue",
    "sivigila-boyaca-events",
    "sivigila-pereira-dengue",
    "sivigila-tulua-dengue",
    "sivigila-caqueta-dengue",
    "sivigila-casanare-dengue",
    "ins-irca-water-quality",
    "pai-valle-municipal",
]

DISEASES = ("dengue", "malaria", "chikunguna", "zika", "leishmaniasis", "ira")


async def main() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    max_records = 12_000 if "--smoke" in sys.argv else None

    async with session_factory() as session:
        await seed_source_catalog(session)
        stuck = list(
            (
                await session.scalars(
                    select(IngestionRun).where(
                        IngestionRun.status.in_(
                            [
                                PipelineStatus.PENDING.value,
                                PipelineStatus.RUNNING.value,
                            ]
                        )
                    )
                )
            ).all()
        )
        for run in stuck:
            run.status = PipelineStatus.FAILED.value
            run.error_message = "cleared by expand_sync_and_train"
        await session.commit()

    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        for source_id in SYNC_SOURCES:
            async with session_factory() as session:
                source = await session.get(DataSource, source_id)
                if source is None:
                    print(f"SKIP missing {source_id}")
                    continue
                try:
                    run = await schedule_source_sync(
                        session, source_id, SourceSyncRequest(max_records=max_records)
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"QUEUE FAIL {source_id}: {exc}")
                    continue
                run_id = run.id
                print(f"RUN {source_id} {run_id}")
            async with session_factory() as session:
                run = await session.get(IngestionRun, run_id)
                assert run is not None
                try:
                    finished = await process_source_sync(
                        session, run, settings, http_client=client
                    )
                    print(
                        f"OK {source_id} accepted={finished.rows_accepted} "
                        f"rejected={finished.rows_rejected} status={finished.status}"
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"FAIL {source_id}: {exc}")

    if "--no-train" in sys.argv:
        await engine.dispose()
        return

    for disease in DISEASES:
        async with session_factory() as session:
            job = ModelTrainingRun(
                disease=disease,
                horizons=[3, 4],
                status=PipelineStatus.PENDING.value,
                parameters={"source": "expand_sync_and_train"},
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id
            print(f"TRAIN queue {disease} {job_id}")
        async with session_factory() as session:
            job = await session.get(ModelTrainingRun, job_id)
            assert job is not None
            try:
                await process_training_job(session, job, settings.model_registry_path)
                await session.refresh(job)
                print(f"TRAIN done {disease} status={job.status}")
            except Exception as exc:  # noqa: BLE001
                print(f"TRAIN fail {disease}: {exc}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
