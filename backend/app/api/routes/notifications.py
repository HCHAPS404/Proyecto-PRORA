from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, SessionDep
from app.core.errors import DomainError
from app.models.entities import NotificationDelivery
from app.schemas.alerts import Channel, NotificationDeliveryResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationDeliveryResponse])
async def list_notifications(
    response: Response,
    user: CurrentUser,
    session: SessionDep,
    channel: Channel | None = None,
    delivery_status: Annotated[
        str | None, Query(alias="status", pattern="^(pending|delivered|unsupported|failed)$")
    ] = None,
    unread_only: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationDelivery]:
    filters = [NotificationDelivery.user_id == user.id]
    if channel:
        filters.append(NotificationDelivery.channel == channel)
    if delivery_status:
        filters.append(NotificationDelivery.status == delivery_status)
    if unread_only:
        filters.extend(
            [
                NotificationDelivery.channel == "in_app",
                NotificationDelivery.status == "delivered",
                NotificationDelivery.read_at.is_(None),
            ]
        )

    total = int(
        await session.scalar(
            select(func.count(NotificationDelivery.id)).where(*filters)
        )
        or 0
    )
    response.headers["X-Total-Count"] = str(total)
    statement = (
        select(NotificationDelivery)
        .where(*filters)
        .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await session.scalars(statement)).all())


async def _owned_notification(
    notification_id: str, user_id: str, session: SessionDep
) -> NotificationDelivery:
    notification = await session.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.id == notification_id,
            NotificationDelivery.user_id == user_id,
        )
    )
    if notification is None:
        raise DomainError("notification_not_found", "La notificacion no existe", 404)
    return notification


@router.patch("/{notification_id}/read", response_model=NotificationDeliveryResponse)
async def mark_notification_read(
    notification_id: str,
    user: CurrentUser,
    session: SessionDep,
) -> NotificationDelivery:
    notification = await _owned_notification(notification_id, user.id, session)
    if notification.channel != "in_app" or notification.status != "delivered":
        raise DomainError(
            "notification_not_readable",
            "Solo las notificaciones entregadas en la plataforma se pueden marcar como leidas",
            409,
        )
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(notification)
    return notification
