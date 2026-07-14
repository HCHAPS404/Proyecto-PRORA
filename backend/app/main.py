from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.db.base import Base
from app.db.session import build_engine, build_session_factory
from app.models import DataSource  # noqa: F401 - register all ORM tables
from app.services.source_catalog import seed_source_catalog


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or get_settings()
    configure_logging(runtime.log_level)
    logger = logging.getLogger("prora")
    engine = build_engine(runtime)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if runtime.auto_create_tables:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with session_factory() as session:
                await seed_source_catalog(session)
        if runtime.uses_ephemeral_jwt_secret:
            logger.warning(
                "Development mode active; configure PRORA_JWT_SECRET for persistent sessions",
                extra={"environment": runtime.environment},
            )
        yield
        await engine.dispose()

    application = FastAPI(
        title=runtime.app_name,
        version=runtime.app_version,
        description=(
            "API segura y asincrona para la plataforma de alerta temprana epidemiologica PRORA. "
            "Los endpoints de datos y prediccion se conectan mediante puertos de dominio."
        ),
        openapi_url=f"{runtime.api_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        debug=runtime.debug,
        lifespan=lifespan,
        contact={"name": "Equipo PRORA"},
        license_info={"name": "Uso sujeto a las politicas del proyecto"},
    )
    application.state.settings = runtime
    application.state.logger = logger
    application.state.engine = engine
    application.state.session_factory = session_factory

    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-Total-Count",
        ],
    )
    application.add_middleware(
        RateLimitMiddleware,
        requests=runtime.rate_limit_requests,
        window_seconds=runtime.rate_limit_window_seconds,
    )
    application.add_middleware(RequestContextMiddleware)

    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(api_router, prefix=runtime.api_prefix)

    @application.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": runtime.app_name,
            "version": runtime.app_version,
            "docs": "/docs",
            "health": "/health",
        }

    return application


app = create_app()
