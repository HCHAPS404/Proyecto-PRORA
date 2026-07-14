from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.security import decode_token
from app.db.session import get_session
from app.models.entities import User, UserRole

bearer = HTTPBearer(auto_error=False, scheme_name="JWTBearer")
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Identity:
    subject: str
    role: UserRole
    jti: str
    is_guest: bool = False


def get_runtime_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    if credentials is None:
        raise DomainError("authentication_required", "Debe iniciar sesion", 401)
    settings = get_runtime_settings(request)
    payload = decode_token(credentials.credentials, settings, "access")
    try:
        role = UserRole(payload.get("role"))
    except ValueError as exc:
        raise DomainError("invalid_token", "El rol del token no es valido", 401) from exc
    return Identity(
        subject=payload["sub"],
        role=role,
        jti=payload["jti"],
        is_guest=role == UserRole.GUEST,
    )


IdentityDep = Annotated[Identity, Depends(get_identity)]


async def get_current_user(identity: IdentityDep, session: SessionDep) -> User:
    if identity.is_guest:
        raise DomainError(
            "registration_required",
            "Esta funcion requiere una cuenta registrada",
            403,
        )
    user = await session.scalar(select(User).where(User.id == identity.subject))
    if user is None or not user.is_active:
        raise DomainError("invalid_session", "La cuenta no existe o esta inactiva", 401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed: UserRole):
    async def dependency(user: CurrentUser) -> User:
        if UserRole(user.role) not in allowed:
            raise DomainError("forbidden", "No tiene permisos para esta operacion", 403)
        return user

    return dependency
