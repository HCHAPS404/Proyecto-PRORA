"""Small, dependency-free scheduler for the verified official-source catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.epidemiology import (
    DataSource,
    IngestionRun,
    PipelineStatus,
    SourceStatus,
)
from app.schemas.sources import SourceSyncRequest


@dataclass(frozen=True, slots=True)
class SourceScheduleResult:
    checked: int
    queued: int
    source_ids: tuple[str, ...]


def _values(field: str, minimum: int, maximum: int) -> set[int]:
    if field == "*":
        return set(range(minimum, maximum + 1))
    values = {int(item) for item in field.split(",")}
    if not values or min(values) < minimum or max(values) > maximum:
        raise ValueError(f"Campo cron fuera de rango: {field}")
    return values


def latest_cron_occurrence(expression: str, now: datetime) -> datetime:
    """Return the latest occurrence for the catalogue's limited cron contract."""

    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("La expresión cron debe tener cinco campos")
    minute_field, hour_field, day_field, month_field, weekday_field = fields
    minutes = _values(minute_field, 0, 59)
    hours = _values(hour_field, 0, 23)
    days = _values(day_field, 1, 31)
    months = _values(month_field, 1, 12)
    weekdays = _values(weekday_field, 0, 6)
    reference = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    reference = reference.astimezone(UTC)

    for offset in range(0, 371):
        candidate_date: date = (reference - timedelta(days=offset)).date()
        if candidate_date.month not in months:
            continue
        day_match = candidate_date.day in days
        # Python: Monday=0; cron: Sunday=0.
        weekday_match = ((candidate_date.weekday() + 1) % 7) in weekdays
        if day_field != "*" and weekday_field != "*":
            if not (day_match or weekday_match):
                continue
        elif not (day_match and weekday_match):
            continue
        for hour in sorted(hours, reverse=True):
            for minute in sorted(minutes, reverse=True):
                candidate = datetime.combine(
                    candidate_date,
                    time(hour=hour, minute=minute, tzinfo=UTC),
                )
                if candidate <= reference:
                    return candidate
    raise ValueError("No se encontró una ocurrencia cron dentro de 370 días")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def enqueue_due_source_syncs(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> SourceScheduleResult:
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    sources = list(
        (
            await session.scalars(
                select(DataSource).where(
                    DataSource.status == SourceStatus.ACTIVE.value,
                    DataSource.refresh_cron.is_not(None),
                )
            )
        ).all()
    )
    busy_source_ids = set(
        (
            await session.scalars(
                select(IngestionRun.source_id).where(
                    IngestionRun.status.in_(
                        [PipelineStatus.PENDING.value, PipelineStatus.RUNNING.value]
                    )
                )
            )
        ).all()
    )
    queued_ids: list[str] = []
    for source in sources:
        if source.id in busy_source_ids or not source.refresh_cron:
            continue
        try:
            due_at = latest_cron_occurrence(source.refresh_cron, reference)
        except ValueError:
            # Invalid catalogue metadata must not create a surprise ingestion.
            continue
        last_checked = _as_utc(source.last_checked_at)
        if last_checked is not None and last_checked >= due_at:
            continue
        configured_codes = (source.configuration or {}).get("scheduled_event_codes")
        event_codes = (
            [int(value) for value in configured_codes]
            if isinstance(configured_codes, list)
            else None
        )
        request = SourceSyncRequest(mode="incremental", event_codes=event_codes)
        session.add(
            IngestionRun(
                source_id=source.id,
                status=PipelineStatus.PENDING.value,
                provenance={
                    "kind": "official_source_sync",
                    "scheduled": True,
                    "scheduled_for": due_at.isoformat(),
                    "request": request.model_dump(mode="json"),
                },
            )
        )
        queued_ids.append(source.id)
        busy_source_ids.add(source.id)
    await session.commit()
    return SourceScheduleResult(
        checked=len(sources),
        queued=len(queued_ids),
        source_ids=tuple(queued_ids),
    )
