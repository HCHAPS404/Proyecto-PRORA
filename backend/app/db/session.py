from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    options: dict = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
    }
    if settings.database_url.startswith("sqlite") and ":memory:" in settings.database_url:
        options["poolclass"] = StaticPool
        options["connect_args"] = {"check_same_thread": False}
    engine = create_async_engine(settings.database_url, **options)
    if settings.database_url.startswith("sqlite"):
        is_memory_database = ":memory:" in settings.database_url

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if not is_memory_database:
                # WAL permits the local dashboard to keep reading while a long
                # ingestion transaction writes. Production deployments use
                # PostgreSQL, but local evaluation must remain responsive too.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
