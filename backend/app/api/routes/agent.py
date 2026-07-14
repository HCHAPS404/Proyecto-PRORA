from __future__ import annotations

from fastapi import APIRouter, Request

from app.agent import AgentService
from app.api.dependencies import SessionDep
from app.schemas.agent import AgentQuery, AgentResponse

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/query", response_model=AgentResponse)
async def query_agent(
    payload: AgentQuery,
    request: Request,
    session: SessionDep,
) -> AgentResponse:
    settings = request.app.state.settings
    secret = getattr(settings, "openai_api_key", None)
    api_key = secret.get_secret_value() if secret else None
    service = AgentService(
        api_key=api_key,
        model=getattr(settings, "openai_model", "gpt-5.4-mini"),
        base_url=getattr(settings, "openai_base_url", "https://api.openai.com/v1"),
    )
    result = await service.answer(session, payload.question, payload.context)
    request_id = getattr(request.state, "request_id", None)
    return AgentResponse(
        answer=result.answer,
        sources=[source.as_dict() for source in result.sources],
        suggested_questions=result.suggested_questions,
        provider=result.provider,
        trace_id=request_id,
    )
