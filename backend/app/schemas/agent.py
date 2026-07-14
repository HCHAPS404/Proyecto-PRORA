from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentQuery(BaseModel):
    question: str = Field(min_length=3, max_length=1200)
    context: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(default=None, max_length=100)


class AgentSourceResponse(BaseModel):
    label: str
    uri: str | None = None
    updated_at: str | None = None


class AgentResponse(BaseModel):
    answer: str
    sources: list[AgentSourceResponse]
    suggested_questions: list[str]
    provider: str
    trace_id: str | None = None
