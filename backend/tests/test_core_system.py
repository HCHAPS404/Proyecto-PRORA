from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


def test_health_ready_openapi_and_request_id(client: TestClient) -> None:
    health = client.get("/health", headers={"X-Request-ID": "health-contract"})
    assert health.status_code == 200
    assert health.headers["X-Request-ID"] == "health-contract"
    assert health.json()["status"] == "ok"
    assert client.get("/ready").json() == {"status": "ready", "database": "up"}
    schema = client.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "PRORA API"


def test_rate_limit_has_machine_readable_response(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'rate.db').as_posix()}",
        jwt_secret=SecretStr("test-only-secret-with-at-least-thirty-two-characters"),
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/auth/guest").status_code == 200
        assert client.post("/api/v1/auth/guest").status_code == 200
        limited = client.post("/api/v1/auth/guest")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limit_exceeded"
        assert "Retry-After" in limited.headers
