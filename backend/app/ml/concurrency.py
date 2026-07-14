"""Database coordination primitives for model publication."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_model_promotion_locks(
    session: AsyncSession,
    disease: str,
    horizons: Iterable[int],
) -> None:
    """Serialize champion/pointer changes for each disease and horizon.

    PostgreSQL transaction-scoped advisory locks coordinate API and worker
    processes without holding a row lock during model fitting. Sorted keys
    prevent deadlocks for jobs publishing both supported horizons. SQLite
    already serializes concurrent writers and is used only for local/test runs.
    """

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for horizon in sorted(set(int(value) for value in horizons)):
        lock_key = _advisory_lock_key(disease, horizon)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )


def _advisory_lock_key(disease: str, horizon: int) -> int:
    payload = f"prora:model-promotion:{disease.strip().lower()}:{int(horizon)}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=True)
