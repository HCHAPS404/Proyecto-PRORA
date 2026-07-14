"""Idempotent evaluation of persisted alert rules and channel deliveries."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.entities import AlertRule, NotificationDelivery, new_id
from app.models.epidemiology import AlertEvent, Forecast, Municipality

ACTIVE_ALERT_STATUSES = ("open", "active")
SUPPORTED_CHANNELS = {"email", "push", "in_app", "webhook"}
OWNED_CHANNEL = "in_app"


@dataclass(frozen=True)
class AlertEvaluationResult:
    alerts_evaluated: int
    rules_evaluated: int
    matches: int
    deliveries_created: int
    deliveries_deduplicated: int


def _normalized(value: str) -> str:
    ascii_value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return " ".join(ascii_value.casefold().strip().split())


def _territory_matches(rule: AlertRule, municipality: Municipality) -> bool:
    targets = {_normalized(str(item)) for item in (rule.territories or []) if str(item).strip()}
    if not targets or targets & {"all", "todos", "national", "nacional", "colombia"}:
        return True
    candidates = {
        _normalized(municipality.code),
        _normalized(municipality.name),
        _normalized(municipality.department_code),
        _normalized(municipality.department_name),
    }
    return bool(targets & candidates)


def _deduplication_key(alert_event_id: str, alert_rule_id: str, channel: str) -> str:
    identity = f"alert-rule-v1|{alert_event_id}|{alert_rule_id}|{channel}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _notification_values(
    *,
    alert: AlertEvent,
    forecast: Forecast,
    municipality: Municipality,
    rule: AlertRule,
    channel: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    risk_percentage = round(forecast.outbreak_probability * 100, 2)
    title = f"Alerta de {forecast.disease} en {municipality.name}"
    message = (
        f"Riesgo {forecast.risk_level} de {risk_percentage:g}% a "
        f"{forecast.horizon_weeks} semanas; {forecast.predicted_cases:.1f} casos estimados "
        f"para {forecast.target_week.isoformat()}."
    )
    owned = channel == OWNED_CHANNEL
    known_channel = channel in SUPPORTED_CHANNELS
    status = "delivered" if owned else "unsupported"
    failure_reason = None
    if not owned:
        failure_reason = (
            "provider_not_configured" if known_channel else "channel_not_supported"
        )
    return {
        "id": new_id(),
        "user_id": rule.user_id,
        "alert_event_id": alert.id,
        "alert_rule_id": rule.id,
        "rule_name": rule.name,
        "disease": forecast.disease,
        "municipality_code": municipality.code,
        "channel": channel,
        "status": status,
        "provider": "prora-in-app" if owned else None,
        "provider_message_id": None,
        "failure_reason": failure_reason,
        "title": title,
        "message": message,
        "payload": {
            "schema_version": "1.0",
            "evaluated_at": evaluated_at.isoformat(),
            "alert_event_id": alert.id,
            "forecast_id": forecast.id,
            "rule": {
                "id": rule.id,
                "name": rule.name,
                "risk_threshold": rule.risk_threshold,
                "horizon_weeks": rule.horizon_weeks,
                "territories": list(rule.territories or []),
                "channels": list(rule.channels or []),
            },
            "signal": {
                "disease": forecast.disease,
                "municipality_code": municipality.code,
                "municipality": municipality.name,
                "department_code": municipality.department_code,
                "department": municipality.department_name,
                "risk_probability": forecast.outbreak_probability,
                "risk_level": forecast.risk_level,
                "predicted_cases": forecast.predicted_cases,
                "interval_lower": forecast.interval_lower,
                "interval_upper": forecast.interval_upper,
                "issued_at": forecast.issued_at.isoformat(),
                "target_week": forecast.target_week.isoformat(),
                "operationally_eligible": forecast.operationally_eligible,
            },
        },
        "deduplication_key": _deduplication_key(alert.id, rule.id, channel),
        "delivered_at": evaluated_at if owned else None,
        "read_at": None,
        "created_at": evaluated_at,
        "updated_at": evaluated_at,
    }


def _chunks(values: Sequence[Any], size: int = 400) -> Iterable[Sequence[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


async def _existing_keys(session: AsyncSession, keys: list[str]) -> set[str]:
    existing: set[str] = set()
    for key_batch in _chunks(keys):
        existing.update(
            (
                await session.scalars(
                    select(NotificationDelivery.deduplication_key).where(
                        NotificationDelivery.deduplication_key.in_(key_batch)
                    )
                )
            ).all()
        )
    return existing


async def _insert_deliveries(
    session: AsyncSession, deliveries: list[dict[str, Any]]
) -> int:
    if not deliveries:
        return 0
    dialect_name = session.get_bind().dialect.name
    inserted = 0
    for delivery_batch in _chunks(deliveries, 200):
        if dialect_name == "postgresql":
            statement = postgresql_insert(NotificationDelivery).values(list(delivery_batch))
            statement = statement.on_conflict_do_nothing(
                index_elements=[NotificationDelivery.deduplication_key]
            )
        elif dialect_name == "sqlite":
            statement = sqlite_insert(NotificationDelivery).values(list(delivery_batch))
            statement = statement.on_conflict_do_nothing(
                index_elements=[NotificationDelivery.deduplication_key]
            )
        else:  # pragma: no cover - supported deployments use PostgreSQL or SQLite
            raise RuntimeError(f"Notification delivery is unsupported for {dialect_name}")
        result = await session.execute(statement)
        if result.rowcount is not None and result.rowcount >= 0:
            inserted += result.rowcount
    return inserted


async def archive_expired_alert_events(session: AsyncSession) -> int:
    """Archive active alerts whose signal is withheld or past its target week."""

    expired_forecasts = select(Forecast.id).where(
        or_(
            Forecast.target_week < date.today(),
            Forecast.operationally_eligible.is_(False),
        )
    )
    result = await session.execute(
        update(AlertEvent)
        .where(
            AlertEvent.status.in_(ACTIVE_ALERT_STATUSES),
            AlertEvent.forecast_id.in_(expired_forecasts),
        )
        .values(status="archived")
    )
    return max(0, int(result.rowcount or 0))


async def evaluate_alert_rules(
    session: AsyncSession,
    *,
    alert_event_ids: set[str] | None = None,
    rule_ids: set[str] | None = None,
    limit: int = 500,
) -> AlertEvaluationResult:
    """Evaluate enabled rules against current operational alert events.

    Evaluation is fail-closed: archived/reviewed/expired alerts and forecasts
    withheld from operations never create deliveries. ``limit`` is a page size,
    not a total cap; keyset pagination guarantees that older compatible alerts are
    eventually evaluated. The deterministic key and database uniqueness make
    repeated worker passes safe.
    """

    await archive_expired_alert_events(session)
    batch_size = max(1, min(limit, 2000))
    alert_statement = (
        select(AlertEvent, Forecast, Municipality)
        .join(Forecast, Forecast.id == AlertEvent.forecast_id)
        .join(Municipality, Municipality.code == Forecast.municipality_code)
        .where(
            AlertEvent.status.in_(ACTIVE_ALERT_STATUSES),
            Forecast.operationally_eligible.is_(True),
            Forecast.target_week >= date.today(),
        )
        .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
    )
    if alert_event_ids is not None:
        if not alert_event_ids:
            return AlertEvaluationResult(0, 0, 0, 0, 0)
        alert_statement = alert_statement.where(AlertEvent.id.in_(alert_event_ids))
    first_alerts = list(
        (await session.execute(alert_statement.limit(batch_size))).all()
    )
    if not first_alerts:
        return AlertEvaluationResult(0, 0, 0, 0, 0)

    rule_statement = select(AlertRule).where(AlertRule.enabled.is_(True))
    if rule_ids is not None:
        if not rule_ids:
            return AlertEvaluationResult(0, 0, 0, 0, 0)
        rule_statement = rule_statement.where(AlertRule.id.in_(rule_ids))
    rules = list((await session.scalars(rule_statement)).all())

    rules_by_signal: dict[tuple[str, int], list[AlertRule]] = defaultdict(list)
    for rule in rules:
        rules_by_signal[(rule.disease.casefold(), rule.horizon_weeks)].append(rule)

    evaluated_at = utcnow()
    alerts_evaluated = 0
    matches = 0
    inserted_total = 0
    candidate_total = 0
    alerts = first_alerts
    while alerts:
        alerts_evaluated += len(alerts)
        deliveries: list[dict[str, Any]] = []
        for alert, forecast, municipality in alerts:
            candidates = rules_by_signal.get(
                (str(forecast.disease).casefold(), int(forecast.horizon_weeks)), []
            )
            for rule in candidates:
                if forecast.outbreak_probability < rule.risk_threshold:
                    continue
                if not _territory_matches(rule, municipality):
                    continue
                matches += 1
                for channel in dict.fromkeys(rule.channels or []):
                    deliveries.append(
                        _notification_values(
                            alert=alert,
                            forecast=forecast,
                            municipality=municipality,
                            rule=rule,
                            channel=str(channel),
                            evaluated_at=evaluated_at,
                        )
                    )

        candidate_total += len(deliveries)
        candidate_keys = [item["deduplication_key"] for item in deliveries]
        existing = await _existing_keys(session, candidate_keys) if candidate_keys else set()
        pending = [item for item in deliveries if item["deduplication_key"] not in existing]
        inserted_total += await _insert_deliveries(session, pending)

        if len(alerts) < batch_size:
            break
        last_alert = alerts[-1][0]
        next_page = alert_statement.where(
            or_(
                AlertEvent.created_at < last_alert.created_at,
                and_(
                    AlertEvent.created_at == last_alert.created_at,
                    AlertEvent.id < last_alert.id,
                ),
            )
        )
        alerts = list((await session.execute(next_page.limit(batch_size))).all())

    return AlertEvaluationResult(
        alerts_evaluated=alerts_evaluated,
        rules_evaluated=len(rules),
        matches=matches,
        deliveries_created=inserted_total,
        deliveries_deduplicated=candidate_total - inserted_total,
    )
