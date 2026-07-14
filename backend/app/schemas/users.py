from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PreferencesResponse(BaseModel):
    theme: Literal["light", "dark", "system"] = "system"
    locale: str = "es-CO"
    timezone: str = "America/Bogota"
    digest_enabled: bool = True
    email_alerts: bool = True
    push_alerts: bool = False
    default_disease: str | None = None
    default_territory: str | None = None
    accessibility: dict[str, Any] = Field(default_factory=dict)


class PreferencesUpdate(BaseModel):
    theme: Literal["light", "dark", "system"] | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=20)
    timezone: str | None = Field(default=None, min_length=3, max_length=80)
    digest_enabled: bool | None = None
    email_alerts: bool | None = None
    push_alerts: bool | None = None
    default_disease: str | None = Field(default=None, max_length=80)
    default_territory: str | None = Field(default=None, max_length=160)
    accessibility: dict[str, Any] | None = None
