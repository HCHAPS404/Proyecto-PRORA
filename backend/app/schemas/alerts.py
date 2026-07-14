from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.risk import Disease

Channel = Literal["email", "push", "in_app", "webhook"]
ChannelCapability = Literal["available", "unsupported", "configuration_only"]


def _channel_capabilities(
    channels: list[Channel], *, subscription: bool = False
) -> dict[str, ChannelCapability]:
    return {
        channel: (
            "configuration_only"
            if channel == "in_app" and subscription
            else "available"
            if channel == "in_app"
            else "unsupported"
        )
        for channel in channels
    }


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    disease: Disease
    territories: list[str] = Field(default_factory=list, max_length=64)
    risk_threshold: float = Field(default=0.7, ge=0, le=1)
    horizon_weeks: Literal[3, 4] = 4
    channels: list[Channel] = Field(
        default_factory=lambda: ["in_app"], min_length=1, max_length=4
    )
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    disease: Disease | None = None
    territories: list[str] | None = Field(default=None, max_length=64)
    risk_threshold: float | None = Field(default=None, ge=0, le=1)
    horizon_weeks: Literal[3, 4] | None = None
    channels: list[Channel] | None = Field(default=None, min_length=1, max_length=4)
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def at_least_one_field(self) -> AlertRuleUpdate:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo")
        return self


class AlertRuleResponse(AlertRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def channel_capabilities(self) -> dict[str, ChannelCapability]:
        return _channel_capabilities(self.channels)


class SubscriptionCreate(BaseModel):
    topic: Literal["critical_alerts", "territory_watch", "epidemiological_summary", "model_drift"]
    target: str = Field(min_length=1, max_length=160)
    frequency: Literal["immediate", "daily", "weekly"] = "weekly"
    channels: list[Channel] = Field(
        default_factory=lambda: ["email"], min_length=1, max_length=4
    )
    enabled: bool = True


class SubscriptionUpdate(BaseModel):
    topic: (
        Literal["critical_alerts", "territory_watch", "epidemiological_summary", "model_drift"]
        | None
    ) = None
    target: str | None = Field(default=None, min_length=1, max_length=160)
    frequency: Literal["immediate", "daily", "weekly"] | None = None
    channels: list[Channel] | None = Field(default=None, min_length=1, max_length=4)
    enabled: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> SubscriptionUpdate:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo")
        return self


class SubscriptionResponse(SubscriptionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def channel_capabilities(self) -> dict[str, ChannelCapability]:
        # Topic subscriptions persist user intent. Delivery schedulers for
        # summaries and model drift are not implemented, so even in-app is not
        # advertised as delivered by this CRUD endpoint.
        return _channel_capabilities(self.channels, subscription=True)


class NotificationDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_event_id: str
    alert_rule_id: str | None
    rule_name: str
    disease: str
    municipality_code: str
    channel: Channel
    status: Literal["pending", "delivered", "unsupported", "failed"]
    provider: str | None
    provider_message_id: str | None
    failure_reason: str | None
    title: str
    message: str
    payload: dict[str, Any]
    delivered_at: datetime | None
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime
