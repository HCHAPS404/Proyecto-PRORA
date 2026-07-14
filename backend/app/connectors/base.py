"""Shared primitives for source-specific Socrata connectors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from .errors import ConnectorConfigurationError
from .socrata import SafeQuery, SocrataClient


@dataclass(slots=True)
class SocrataSourceConnector:
    client: SocrataClient
    dataset_id: str | None
    source_name: str
    page_size: int = 5_000

    def require_dataset_id(self) -> str:
        if not self.dataset_id:
            raise ConnectorConfigurationError(
                f"{self.source_name} has no verified tabular dataset configured; "
                "set its dataset ID environment variable"
            )
        return self.dataset_id

    async def pages(
        self, query: SafeQuery | None = None, *, max_records: int | None = None
    ) -> AsyncIterator[list[dict[str, Any]]]:
        dataset_id = self.require_dataset_id()
        async for page in self.client.paginate(
            dataset_id, query=query, page_size=self.page_size, max_records=max_records
        ):
            yield page
