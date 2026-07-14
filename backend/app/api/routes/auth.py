from __future__ import annotations

import hmac
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import IdentityDep, SessionDep
from app.core.errors import DomainError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    fingerprint_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models.entities import RefreshSession, User, UserRole
from app.schemas.auth import (
    GuestResponse,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _client_metadata(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent", "")[:300] or None


async def _issue_pair(
    request: Request, session: SessionDep, user: User, family_id: str | None = None
) -> TokenPair:
    settings = request.app.state.settings
    access = create_access_token(user.id, user.role, settings)
    refresh = create_refresh_token(user.id, user.role, settings)
    ip, user_agent = _client_metadata(request)
    session.add(
        RefreshSession(
            jti=refresh.jti,
            family_id=family_id or str(uuid4()),
            user_id=user.id,
            token_hash=fingerprint_token(refresh.token),
            expires_at=refresh.expires_at,
            ip_address=ip,
            user_agent=user_agent,
        )
    )
    return TokenPair(
        access_token=access.token,
        refresh_token=refresh.token,
        expires_in=settings.access_token_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request, session: SessionDep) -> TokenPair:
    email = payload.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise DomainError("email_already_registered", "El correo ya esta registrado", 409)
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=UserRole.USER.value,
        preferences={},
    )
    session.add(user)
    try:
        await session.flush()
        pair = await _issue_pair(request, session, user)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DomainError("email_already_registered", "El correo ya esta registrado", 409) from exc
    return pair


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, session: SessionDep) -> TokenPair:
    user = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise DomainError("invalid_credentials", "Correo o contrasena incorrectos", 401)
    if not user.is_active:
        raise DomainError("account_disabled", "La cuenta esta inactiva", 403)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    pair = await _issue_pair(request, session, user)
    await session.commit()
    return pair


@router.post("/guest", response_model=TokenPair)
async def guest_access(request: Request) -> TokenPair:
    settings = request.app.state.settings
    guest_id = f"guest:{uuid4()}"
    access = create_access_token(guest_id, UserRole.GUEST.value, settings)
    return TokenPair(
        access_token=access.token,
        expires_in=settings.access_token_minutes * 60,
        user=GuestResponse(id=guest_id),
    )


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, request: Request, session: SessionDep) -> TokenPair:
    settings = request.app.state.settings
    claims = decode_token(payload.refresh_token, settings, "refresh")
    stored = await session.scalar(
        select(RefreshSession).where(RefreshSession.jti == claims["jti"]).with_for_update()
    )
    if stored is None or not hmac.compare_digest(
        stored.token_hash, fingerprint_token(payload.refresh_token)
    ):
        raise DomainError("invalid_refresh_token", "La sesion de renovacion no es valida", 401)
    if stored.revoked_at is not None:
        await session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.family_id == stored.family_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
        raise DomainError("refresh_token_reused", "Se detecto reutilizacion del token", 401)
    if _as_aware(stored.expires_at) <= datetime.now(UTC):
        raise DomainError("refresh_token_expired", "La sesion de renovacion expiro", 401)
    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise DomainError("invalid_session", "La cuenta no existe o esta inactiva", 401)
    stored.revoked_at = datetime.now(UTC)
    pair = await _issue_pair(request, session, user, family_id=stored.family_id)
    # El jti nuevo puede recuperarse de las entidades pendientes sin exponer el token.
    for candidate in session.new:
        if isinstance(candidate, RefreshSession) and candidate.family_id == stored.family_id:
            stored.replaced_by_jti = candidate.jti
            break
    await session.commit()
    return pair


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest, request: Request, session: SessionDep) -> MessageResponse:
    claims = decode_token(payload.refresh_token, request.app.state.settings, "refresh")
    stored = await session.scalar(select(RefreshSession).where(RefreshSession.jti == claims["jti"]))
    if stored and hmac.compare_digest(stored.token_hash, fingerprint_token(payload.refresh_token)):
        stored.revoked_at = stored.revoked_at or datetime.now(UTC)
        await session.commit()
    return MessageResponse(message="Sesion cerrada")


@router.get("/me", response_model=UserResponse | GuestResponse)
async def me(identity: IdentityDep, session: SessionDep) -> UserResponse | GuestResponse:
    if identity.is_guest:
        return GuestResponse(id=identity.subject)
    user = await session.get(User, identity.subject)
    if user is None or not user.is_active:
        raise DomainError("invalid_session", "La cuenta no existe o esta inactiva", 401)
    return UserResponse.model_validate(user)
