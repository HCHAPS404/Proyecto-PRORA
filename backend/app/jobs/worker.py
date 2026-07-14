"""Small, durable database worker for PRORA model jobs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import build_engine, build_session_factory
from app.jobs.ingestion import claim_ingestion_job, process_ingestion_job
from app.jobs.training import claim_training_job, process_training_job
from app.services.alert_delivery import evaluate_alert_rules
from app.services.source_schedule import enqueue_due_source_syncs


async def run(*, once: bool, poll_seconds: float) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("prora.worker")
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    next_schedule_check = 0.0
    try:
        while True:
            job = None
            async with factory() as session:
                if not once and time.monotonic() >= next_schedule_check:
                    try:
                        schedule = await enqueue_due_source_syncs(session)
                        next_schedule_check = time.monotonic() + 300.0
                        if schedule.queued:
                            logger.info(
                                "official_source_syncs_queued",
                                extra={
                                    "queued": schedule.queued,
                                    "source_ids": list(schedule.source_ids),
                                },
                            )
                    except Exception:
                        await session.rollback()
                        next_schedule_check = time.monotonic() + 60.0
                        logger.exception("official_source_schedule_failed")
                ingestion = await claim_ingestion_job(session)
                if ingestion is not None:
                    job = ingestion
                    logger.info("ingestion_job_started", extra={"job_id": ingestion.id})
                    await process_ingestion_job(session, ingestion, settings)
                    logger.info("ingestion_job_finished", extra={"job_id": ingestion.id})
                else:
                    training = await claim_training_job(session)
                    if training is not None:
                        job = training
                        logger.info("training_job_started", extra={"job_id": training.id})
                        await process_training_job(session, training, settings.model_registry_path)
                        logger.info("training_job_finished", extra={"job_id": training.id})
                try:
                    evaluation = await evaluate_alert_rules(session)
                    await session.commit()
                    if evaluation.deliveries_created:
                        logger.info(
                            "alert_deliveries_created",
                            extra={
                                "deliveries_created": evaluation.deliveries_created,
                                "matches": evaluation.matches,
                                "alerts_evaluated": evaluation.alerts_evaluated,
                            },
                        )
                except Exception:
                    await session.rollback()
                    logger.exception("alert_delivery_evaluation_failed")
            if once:
                return
            if job is None:
                await asyncio.sleep(poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="PRORA background worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    arguments = parser.parse_args()
    asyncio.run(run(once=arguments.once, poll_seconds=max(0.5, arguments.poll_seconds)))


if __name__ == "__main__":
    main()
