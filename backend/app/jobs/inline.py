"""Run queued ingestion/training jobs inside the API process (Render free)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.config import Settings, get_settings
from app.db.session import build_engine, build_session_factory
from app.jobs.ingestion import process_ingestion_job
from app.jobs.training import process_training_job
from app.models.epidemiology import IngestionRun, ModelTrainingRun, PipelineStatus

logger = logging.getLogger("prora.jobs_inline")


async def run_ingestion_inline(run_id: str) -> None:
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
            if run is None:
                logger.warning("inline_ingestion_missing", extra={"run_id": run_id})
                return
            if run.status != PipelineStatus.PENDING.value:
                logger.info(
                    "inline_ingestion_skip",
                    extra={"run_id": run_id, "status": run.status},
                )
                return
            run.status = PipelineStatus.RUNNING.value
            run.started_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(run)
            logger.info("inline_ingestion_started", extra={"run_id": run_id})
            await process_ingestion_job(session, run, settings)
            logger.info("inline_ingestion_finished", extra={"run_id": run_id})
    except Exception:
        logger.exception("inline_ingestion_failed", extra={"run_id": run_id})
    finally:
        await engine.dispose()


async def run_training_inline(job_id: str, settings: Settings | None = None) -> None:
    runtime = settings or get_settings()
    engine = build_engine(runtime)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            job = await session.get(ModelTrainingRun, job_id)
            if job is None:
                logger.warning("inline_training_missing", extra={"job_id": job_id})
                return
            if job.status != PipelineStatus.PENDING.value:
                logger.info(
                    "inline_training_skip",
                    extra={"job_id": job_id, "status": job.status},
                )
                return
            job.status = PipelineStatus.RUNNING.value
            job.started_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(job)
            logger.info("inline_training_started", extra={"job_id": job_id})
            await process_training_job(session, job, runtime.model_registry_path)
            logger.info("inline_training_finished", extra={"job_id": job_id})
    except Exception:
        logger.exception("inline_training_failed", extra={"job_id": job_id})
    finally:
        await engine.dispose()
