from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDep
from app.core.errors import DomainError
from app.models.entities import Subscription
from app.schemas.alerts import (
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(user: CurrentUser, session: SessionDep) -> list[Subscription]:
    statement = (
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
    )
    return list((await session.scalars(statement)).all())


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: SubscriptionCreate, user: CurrentUser, session: SessionDep
) -> Subscription:
    subscription = Subscription(user_id=user.id, **payload.model_dump())
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def _owned_subscription(
    subscription_id: str, user: CurrentUser, session: SessionDep
) -> Subscription:
    subscription = await session.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    if subscription is None:
        raise DomainError("subscription_not_found", "La suscripcion no existe", 404)
    return subscription


@router.patch("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    payload: SubscriptionUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> Subscription:
    subscription = await _owned_subscription(subscription_id, user, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(subscription, field, value)
    await session.commit()
    await session.refresh(subscription)
    return subscription


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: str, user: CurrentUser, session: SessionDep
) -> Response:
    subscription = await _owned_subscription(subscription_id, user, session)
    await session.delete(subscription)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
