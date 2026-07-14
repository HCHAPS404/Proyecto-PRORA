from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        auto_create_tables=True,
        jwt_secret=SecretStr("test-only-secret-with-at-least-thirty-two-characters"),
        rate_limit_requests=500,
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def registered(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "analista@example.org",
            "full_name": "Analista PRORA",
            "password": "SecurePass123!",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth_headers(registered: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['access_token']}"}
