from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.errors import DomainError
from app.schemas.system import HealthResponse, ReadyResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Estado del proceso")
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadyResponse, summary="Disponibilidad de dependencias")
async def ready(request: Request) -> ReadyResponse:
    try:
        async with request.app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise DomainError(
            "database_unavailable", "La base de datos no esta disponible", 503
        ) from exc
    return ReadyResponse(status="ready", database="up")
