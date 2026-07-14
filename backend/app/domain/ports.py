from __future__ import annotations

from datetime import date
from typing import Any, Protocol


class PredictionProvider(Protocol):
    """Contrato que deben implementar los modelos ML sin depender de FastAPI."""

    async def predict(
        self, *, disease: str, territory_code: str, as_of: date, horizon_weeks: int
    ) -> list[dict[str, Any]]: ...

    async def explain(self, *, prediction_id: str) -> dict[str, Any]: ...


class PublicHealthDataSource(Protocol):
    """Contrato para SIVIGILA, PAI, IDEAM, DANE u otras fuentes."""

    source_name: str

    async def healthcheck(self) -> bool: ...

    async def sync(self, *, since: date | None = None) -> dict[str, int]: ...
