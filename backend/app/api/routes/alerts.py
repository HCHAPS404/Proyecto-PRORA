from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDep
from app.core.errors import DomainError
from app.models.entities import AlertRule
from app.schemas.alerts import AlertRuleCreate, AlertRuleResponse, AlertRuleUpdate
from app.services.alert_delivery import evaluate_alert_rules

router = APIRouter(prefix="/alerts", tags=["alert rules"])


@router.get("", response_model=list[AlertRuleResponse])
async def list_alerts(
    user: CurrentUser,
    session: SessionDep,
    enabled: bool | None = None,
    disease: str | None = Query(default=None, max_length=80),
) -> list[AlertRule]:
    statement = select(AlertRule).where(AlertRule.user_id == user.id)
    if enabled is not None:
        statement = statement.where(AlertRule.enabled == enabled)
    if disease:
        statement = statement.where(AlertRule.disease == disease)
    statement = statement.order_by(AlertRule.created_at.desc())
    return list((await session.scalars(statement)).all())


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    payload: AlertRuleCreate, user: CurrentUser, session: SessionDep
) -> AlertRule:
    rule = AlertRule(user_id=user.id, **payload.model_dump())
    session.add(rule)
    await session.flush()
    await evaluate_alert_rules(session, rule_ids={rule.id})
    await session.commit()
    await session.refresh(rule)
    return rule


async def _owned_rule(rule_id: str, user: CurrentUser, session: SessionDep) -> AlertRule:
    rule = await session.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user.id)
    )
    if rule is None:
        raise DomainError("alert_not_found", "La regla de alerta no existe", 404)
    return rule


@router.get("/{rule_id}", response_model=AlertRuleResponse)
async def get_alert(rule_id: str, user: CurrentUser, session: SessionDep) -> AlertRule:
    return await _owned_rule(rule_id, user, session)


@router.patch("/{rule_id}", response_model=AlertRuleResponse)
async def update_alert(
    rule_id: str, payload: AlertRuleUpdate, user: CurrentUser, session: SessionDep
) -> AlertRule:
    rule = await _owned_rule(rule_id, user, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await session.flush()
    if rule.enabled:
        await evaluate_alert_rules(session, rule_ids={rule.id})
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(rule_id: str, user: CurrentUser, session: SessionDep) -> Response:
    rule = await _owned_rule(rule_id, user, session)
    await session.delete(rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
