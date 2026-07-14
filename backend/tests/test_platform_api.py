from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.schemas.risk import TrainingJobResponse


def test_public_platform_contracts_are_available(client: TestClient) -> None:
    sources = client.get("/api/v1/sources")
    assert sources.status_code == 200
    assert len(sources.json()) >= 8
    assert any(item["id"] == "dane-divipola" for item in sources.json())

    risk_map = client.get("/api/v1/risk/map?disease=dengue&horizon=4")
    assert risk_map.status_code == 200
    assert risk_map.json() == []

    alerts = client.get("/api/v1/risk/alerts")
    assert alerts.status_code == 200
    assert alerts.json() == []

    summary = client.get("/api/v1/analytics/summary?disease=dengue&territory=national")
    assert summary.status_code == 200
    assert summary.json()["data_status"] == "no_data"
    assert summary.json()["latest"] is None

    series = client.get("/api/v1/analytics/series?disease=dengue&territory=national")
    assert series.status_code == 200
    assert series.json()["points"] == []
    assert series.json()["metadata"]["synthetic_values"] is False

    current_reference = client.get(
        "/api/v1/analytics/current-reference?disease=dengue&territory=national"
    )
    assert current_reference.status_code == 404
    assert current_reference.json()["error"]["code"] == "current_reference_not_found"

    forecasts = client.get(
        "/api/v1/analytics/forecast-series?disease=dengue&territory=national&horizon=4"
    )
    assert forecasts.status_code == 200
    assert forecasts.json()["points"] == []
    assert forecasts.json()["metadata"]["status"] == "no_operational_forecasts"

    agent = client.post(
        "/api/v1/agent/query",
        json={"question": "¿Qué fuentes están disponibles?"},
    )
    assert agent.status_code == 200
    assert agent.json()["provider"] == "deterministic"
    assert agent.json()["sources"]


def test_model_training_requires_operational_role(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/models/train",
        headers=auth_headers,
        json={"disease": "dengue", "horizons": [3, 4]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_openapi_exposes_full_platform(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    expected = {
        "/api/v1/auth/register",
        "/api/v1/notifications",
        "/api/v1/sources",
        "/api/v1/risk/map",
        "/api/v1/risk/alerts",
        "/api/v1/models/train",
        "/api/v1/analytics/summary",
        "/api/v1/analytics/series",
        "/api/v1/analytics/current-reference",
        "/api/v1/analytics/forecast-series",
        "/api/v1/agent/query",
    }
    assert expected.issubset(paths)


def test_training_job_response_maps_orm_primary_key_to_public_job_id() -> None:
    response = TrainingJobResponse.model_validate(
        SimpleNamespace(
            id="training-123",
            disease="dengue",
            horizons=[3, 4],
            status="pending",
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
            result={},
            error_message=None,
        ),
        from_attributes=True,
    )

    assert response.job_id == "training-123"
