"""Small ingestion boundary that preserves rejected rows and quality reports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .normalizers import RowNormalizationError
from .quality import QualityReport

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class IngestionEnvelope(Generic[T]):
    record: T | None
    quality: QualityReport | None
    raw: Mapping[str, Any]
    rejected_reason: str | None = None


def normalize_page(
    rows: list[dict[str, Any]],
    normalizer: Callable[[Mapping[str, Any]], tuple[T, QualityReport]],
) -> list[IngestionEnvelope[T]]:
    output: list[IngestionEnvelope[T]] = []
    for row in rows:
        try:
            record, quality = normalizer(row)
            output.append(IngestionEnvelope(record=record, quality=quality, raw=row))
        except RowNormalizationError as exc:
            output.append(
                IngestionEnvelope(
                    record=None,
                    quality=None,
                    raw=row,
                    rejected_reason=str(exc),
                )
            )
    return output
