from fastapi.testclient import TestClient


def test_preferences_round_trip(client: TestClient, auth_headers: dict[str, str]) -> None:
    defaults = client.get("/api/v1/preferences", headers=auth_headers)
    assert defaults.status_code == 200
    assert defaults.json()["theme"] == "system"

    updated = client.patch(
        "/api/v1/preferences",
        headers=auth_headers,
        json={"theme": "dark", "default_disease": "dengue", "push_alerts": True},
    )
    assert updated.status_code == 200
    assert updated.json()["theme"] == "dark"
    assert updated.json()["default_disease"] == "dengue"


def test_alert_crud_is_scoped_to_owner(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/alerts",
        headers=auth_headers,
        json={
            "name": "Dengue Valle",
            "disease": "dengue",
            "territories": ["76001", "76834"],
            "risk_threshold": 0.82,
            "horizon_weeks": 4,
            "channels": ["email", "in_app"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["channel_capabilities"] == {
        "email": "unsupported",
        "in_app": "available",
    }
    rule_id = created.json()["id"]

    listed = client.get("/api/v1/alerts?enabled=true&disease=dengue", headers=auth_headers)
    assert listed.status_code == 200
    assert [rule["id"] for rule in listed.json()] == [rule_id]

    updated = client.patch(
        f"/api/v1/alerts/{rule_id}", headers=auth_headers, json={"enabled": False}
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/v1/alerts/{rule_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/alerts/{rule_id}", headers=auth_headers).status_code == 404


def test_subscription_crud(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/subscriptions",
        headers=auth_headers,
        json={
            "topic": "epidemiological_summary",
            "target": "Colombia",
            "frequency": "weekly",
            "channels": ["email"],
        },
    )
    assert created.status_code == 201
    assert created.json()["channel_capabilities"] == {"email": "unsupported"}
    subscription_id = created.json()["id"]
    assert (
        client.patch(
            f"/api/v1/subscriptions/{subscription_id}",
            headers=auth_headers,
            json={"frequency": "daily"},
        ).json()["frequency"]
        == "daily"
    )
    assert (
        client.delete(f"/api/v1/subscriptions/{subscription_id}", headers=auth_headers).status_code
        == 204
    )
