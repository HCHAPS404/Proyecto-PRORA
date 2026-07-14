from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.epidemiology import DataSource, IngestionRun, SourceStatus
from app.services.source_schedule import enqueue_due_source_syncs, latest_cron_occurrence


def test_latest_cron_occurrence_supports_catalog_patterns() -> None:
    reference = datetime(2026, 7, 13, 14, 0, tzinfo=UTC)  # Monday

    assert latest_cron_occurrence("15 3 * * *", reference) == datetime(
        2026, 7, 13, 3, 15, tzinfo=UTC
    )
    assert latest_cron_occurrence("0 12 * * 5", reference) == datetime(
        2026, 7, 10, 12, 0, tzinfo=UTC
    )
    assert latest_cron_occurrence("0 5 10 1,4,7,10 *", reference) == datetime(
        2026, 7, 10, 5, 0, tzinfo=UTC
    )


def test_due_source_is_queued_once_with_auditable_schedule(client: TestClient) -> None:
    async def exercise() -> tuple[int, int, list[IngestionRun]]:
        async with client.app.state.session_factory() as session:
            catalog_sources = list((await session.scalars(select(DataSource))).all())
            for source in catalog_sources:
                source.refresh_cron = None
            session.add(
                DataSource(
                    id="scheduled-test-source",
                    name="Fuente programada",
                    institution="INS",
                    source_type="socrata",
                    status=SourceStatus.ACTIVE.value,
                    refresh_cron="15 3 * * *",
                    last_checked_at=datetime(2026, 7, 12, 3, 0, tzinfo=UTC),
                    configuration={},
                )
            )
            await session.commit()
            first = await enqueue_due_source_syncs(
                session, now=datetime(2026, 7, 13, 14, 0, tzinfo=UTC)
            )
            second = await enqueue_due_source_syncs(
                session, now=datetime(2026, 7, 13, 14, 1, tzinfo=UTC)
            )
            runs = list(
                (
                    await session.scalars(
                        select(IngestionRun).where(
                            IngestionRun.source_id == "scheduled-test-source"
                        )
                    )
                ).all()
            )
            return first.queued, second.queued, runs

    first_queued, second_queued, runs = asyncio.run(exercise())

    assert first_queued == 1
    assert second_queued == 0
    assert len(runs) == 1
    assert runs[0].status == "pending"
    assert runs[0].provenance["scheduled"] is True
    assert runs[0].provenance["scheduled_for"] == "2026-07-13T03:15:00+00:00"
