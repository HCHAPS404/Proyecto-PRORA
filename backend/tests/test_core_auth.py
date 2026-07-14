from fastapi.testclient import TestClient


def test_register_login_me_and_error_envelope(client: TestClient) -> None:
    weak = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.org", "full_name": "Weak User", "password": "short"},
        headers={"X-Request-ID": "contract-test-id"},
    )
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "validation_error"
    assert weak.json()["error"]["request_id"] == "contract-test-id"

    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "USER@example.org",
            "full_name": "Usuario Salud",
            "password": "StrongPassword123!",
        },
    )
    assert registered.status_code == 201
    body = registered.json()
    assert body["token_type"] == "bearer"
    assert body["refresh_token"]
    assert body["user"]["email"] == "user@example.org"
    assert body["user"]["role"] == "user"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["full_name"] == "Usuario Salud"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.org", "password": "StrongPassword123!"},
    )
    assert login.status_code == 200
    assert login.json()["access_token"] != body["access_token"]

    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.org",
            "full_name": "Duplicado",
            "password": "StrongPassword123!",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "email_already_registered"


def test_refresh_rotation_and_reuse_detection(client: TestClient, registered: dict) -> None:
    original = registered["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    successor = rotated.json()["refresh_token"]
    assert successor != original

    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "refresh_token_reused"

    revoked_family = client.post("/api/v1/auth/refresh", json={"refresh_token": successor})
    assert revoked_family.status_code == 401


def test_guest_identity_cannot_write_private_resources(client: TestClient) -> None:
    guest = client.post("/api/v1/auth/guest")
    assert guest.status_code == 200
    token = guest.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "guest"

    private = client.get("/api/v1/alerts", headers={"Authorization": f"Bearer {token}"})
    assert private.status_code == 403
    assert private.json()["error"]["code"] == "registration_required"
