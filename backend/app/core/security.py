from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.errors import DomainError

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class EncodedToken:
    token: str
    jti: str
    expires_at: datetime


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def create_token(
    *, subject: str, role: str, token_type: str, settings: Settings, lifetime: timedelta
) -> EncodedToken:
    now = datetime.now(UTC)
    expires_at = now + lifetime
    jti = str(uuid4())
    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": "prora-api",
        "aud": "prora-clients",
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return EncodedToken(token=token, jti=jti, expires_at=expires_at)


def create_access_token(subject: str, role: str, settings: Settings) -> EncodedToken:
    return create_token(
        subject=subject,
        role=role,
        token_type="access",
        settings=settings,
        lifetime=timedelta(minutes=settings.access_token_minutes),
    )


def create_refresh_token(subject: str, role: str, settings: Settings) -> EncodedToken:
    return create_token(
        subject=subject,
        role=role,
        token_type="refresh",
        settings=settings,
        lifetime=timedelta(days=settings.refresh_token_days),
    )


def decode_token(token: str, settings: Settings, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience="prora-clients",
            issuer="prora-api",
        )
    except jwt.ExpiredSignatureError as exc:
        raise DomainError("token_expired", "El token ha expirado", 401) from exc
    except jwt.PyJWTError as exc:
        raise DomainError("invalid_token", "El token no es valido", 401) from exc
    if payload.get("type") != expected_type or not payload.get("sub") or not payload.get("jti"):
        raise DomainError("invalid_token", "El tipo o contenido del token no es valido", 401)
    return payload


def fingerprint_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
