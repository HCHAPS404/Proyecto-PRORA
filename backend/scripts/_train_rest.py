"""Retrain remaining prioritized diseases after dengue expand sync."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.jobs.training import process_training_job
from app.models.epidemiology import ModelTrainingRun, PipelineStatus

DISEASES = ("malaria", "chikunguna", "zika", "leishmaniasis", "ira")


async def main() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    for disease in DISEASES:
        async with session_factory() as session:
            job = ModelTrainingRun(
                disease=disease,
                horizons=[3, 4],
                status=PipelineStatus.PENDING.value,
                parameters={"source": "expand"},
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id
            print("queued", disease, job_id, flush=True)
        async with session_factory() as session:
            job = await session.get(ModelTrainingRun, job_id)
            assert job is not None
            print("training", disease, flush=True)
            await process_training_job(session, job, settings.model_registry_path)
            await session.refresh(job)
            print("done", disease, job.status, flush=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
