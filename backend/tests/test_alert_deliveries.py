from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.security import create_access_token
from app.models.entities import NotificationDelivery, User
from app.models.epidemiology import AlertEvent, Forecast, ModelVersion, Municipality
from app.services.alert_delivery import evaluate_alert_rules


def _seed_operational_alert(
    client: TestClient,
    *,
    code: str = "76001",
    eligible: bool = True,
    status: str = "open",
    probability: float = 0.91,
) -> str:
    async def seed() -> str:
        async with client.app.state.session_factory() as session:
            session.add(
                Municipality(
                    code=code,
                    name="Cali",
                    department_code="76",
                    department_name="Valle del Cauca",
                )
            )
            model = ModelVersion(
                disease="dengue",
                horizon_weeks=4,
                version=f"delivery-test-{code}",
                stage="champion",
                artifact_uri=f"models/delivery-test-{code}",
            )
            session.add(model)
            await session.flush()
            forecast = Forecast(
                municipality_code=code,
                disease="dengue",
                target_week=date.today() + timedelta(weeks=4),
                horizon_weeks=4,
                predicted_cases=24.5,
                interval_lower=17,
                interval_upper=33,
                outbreak_probability=probability,
                risk_level="critical",
                observation_cutoff=date.today(),
                observation_age_days=0,
                operationally_eligible=eligible,
                model_version_id=model.id,
            )
            session.add(forecast)
            await session.flush()
            alert = AlertEvent(forecast_id=forecast.id, threshold=0.8, status=status)
            session.add(alert)
            await session.commit()
            return alert.id

    return asyncio.run(seed())


def test_rule_evaluation_creates_honest_idempotent_deliveries(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed_operational_alert(client)
    created = client.post(
        "/api/v1/alerts",
        headers=auth_headers,
        json={
            "name": "Dengue operativo Cali",
            "disease": "dengue",
            "territories": ["76001"],
            "risk_threshold": 0.85,
            "horizon_weeks": 4,
            "channels": ["in_app", "email"],
        },
    )
    assert created.status_code == 201, created.text

    deliveries = client.get("/api/v1/notifications", headers=auth_headers)
    assert deliveries.status_code == 200, deliveries.text
    assert deliveries.headers["x-total-count"] == "2"
    by_channel = {item["channel"]: item for item in deliveries.json()}
    assert by_channel["in_app"]["status"] == "delivered"
    assert by_channel["in_app"]["provider"] == "prora-in-app"
    assert by_channel["in_app"]["delivered_at"]
    assert by_channel["email"]["status"] == "unsupported"
    assert by_channel["email"]["provider"] is None
    assert by_channel["email"]["delivered_at"] is None
    assert by_channel["email"]["failure_reason"] == "provider_not_configured"
    assert by_channel["email"]["payload"]["signal"]["operationally_eligible"] is True

    updated = client.patch(
        f"/api/v1/alerts/{created.json()['id']}",
        headers=auth_headers,
        json={"notes": "La reevaluacion no debe duplicar entregas"},
    )
    assert updated.status_code == 200
    repeated = client.get("/api/v1/notifications", headers=auth_headers)
    assert repeated.headers["x-total-count"] == "2"

    unread = client.get("/api/v1/notifications?unread_only=true", headers=auth_headers)
    assert [item["channel"] for item in unread.json()] == ["in_app"]
    marked = client.patch(
        f"/api/v1/notifications/{by_channel['in_app']['id']}/read", headers=auth_headers
    )
    assert marked.status_code == 200
    assert marked.json()["read_at"]
    assert (
        client.get("/api/v1/notifications?unread_only=true", headers=auth_headers).headers[
            "x-total-count"
        ]
        == "0"
    )
    unsupported_read = client.patch(
        f"/api/v1/notifications/{by_channel['email']['id']}/read", headers=auth_headers
    )
    assert unsupported_read.status_code == 409

    deleted = client.delete(f"/api/v1/alerts/{created.json()['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    retained_trace = client.get("/api/v1/notifications", headers=auth_headers).json()
    assert len(retained_trace) == 2
    assert all(item["alert_rule_id"] is None for item in retained_trace)
    assert all(item["rule_name"] == "Dengue operativo Cali" for item in retained_trace)


def test_periodic_evaluation_is_idempotent_and_fail_closed(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed_operational_alert(client, code="05001", eligible=False)
    created = client.post(
        "/api/v1/alerts",
        headers=auth_headers,
        json={
            "name": "Dengue nacional",
            "disease": "dengue",
            "territories": [],
            "risk_threshold": 0.7,
            "horizon_weeks": 4,
            "channels": ["in_app"],
        },
    )
    assert created.status_code == 201
    assert client.get("/api/v1/notifications", headers=auth_headers).json() == []

    async def evaluate_twice() -> tuple[int, int, int]:
        async with client.app.state.session_factory() as session:
            first = await evaluate_alert_rules(session)
            await session.commit()
            second = await evaluate_alert_rules(session)
            await session.commit()
            count = int(
                await session.scalar(select(func.count(NotificationDelivery.id))) or 0
            )
            return first.deliveries_created, second.deliveries_created, count

    assert asyncio.run(evaluate_twice()) == (0, 0, 0)


def test_alert_review_exposes_trace_and_list_keeps_compatible_pagination(
    client: TestClient,
    registered: dict,
) -> None:
    alert_id = _seed_operational_alert(client)
    user_id = registered["user"]["id"]

    async def promote() -> None:
        async with client.app.state.session_factory() as session:
            await session.execute(
                update(User).where(User.id == user_id).values(role="analyst")
            )
            await session.commit()

    asyncio.run(promote())
    token = create_access_token(user_id, "analyst", client.app.state.settings).token
    analyst_headers = {"Authorization": f"Bearer {token}"}

    listed = client.get("/api/v1/risk/alerts?offset=0&limit=1")
    assert listed.status_code == 200
    assert listed.headers["x-total-count"] == "1"
    assert listed.json()[0]["reviewed_at"] is None
    assert listed.json()[0]["reviewed_by"] is None
    assert listed.json()[0]["review_notes"] is None
    paged_past = client.get("/api/v1/risk/alerts?offset=1&limit=1")
    assert paged_past.headers["x-total-count"] == "1"
    assert paged_past.json() == []

    reviewed = client.post(
        f"/api/v1/risk/alerts/{alert_id}/review",
        headers=analyst_headers,
        json={"status": "acknowledged", "notes": "Validada con vigilancia territorial"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_by"] == user_id
    assert reviewed.json()["reviewed_at"]
    assert reviewed.json()["review_notes"] == "Validada con vigilancia territorial"
