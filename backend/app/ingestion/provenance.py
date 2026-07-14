"""Immutable source lineage attached to every canonical observation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Provenance:
    source_system: str
    dataset_id: str
    source_url: str
    retrieved_at: datetime
    raw_record_sha256: str
    schema_version: str = "1.0"
    attribution: str | None = None
    license_name: str | None = None


def build_provenance(
    row: Mapping[str, Any],
    *,
    source_system: str,
    dataset_id: str,
    source_url: str | None = None,
    attribution: str | None = None,
    license_name: str | None = None,
    retrieved_at: datetime | None = None,
) -> Provenance:
    canonical = json.dumps(
        row,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return Provenance(
        source_system=source_system,
        dataset_id=dataset_id,
        source_url=source_url or f"https://www.datos.gov.co/resource/{dataset_id}.json",
        retrieved_at=retrieved_at or datetime.now(UTC),
        raw_record_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        attribution=attribution,
        license_name=license_name,
    )
