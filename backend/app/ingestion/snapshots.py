"""Immutable NDJSON snapshots and machine-readable manifests for official sources."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class SnapshotArtifact:
    object_path: str
    manifest_path: str
    content_bytes: int
    row_count: int
    page_count: int
    sha256: str
    schema_sha256: str
    retrieved_at: datetime
    manifest: dict[str, Any]
    media_type: str = "application/x-ndjson"


class RawSnapshotWriter:
    """Writes once under a run UUID; final files are published atomically."""

    def __init__(
        self,
        *,
        root: str | Path,
        source_id: str,
        run_id: str,
        source_url: str,
        dataset_id: str | None,
        query: dict[str, Any],
        publication: dict[str, Any] | None = None,
    ) -> None:
        if not _SAFE_SEGMENT.fullmatch(source_id) or not _SAFE_SEGMENT.fullmatch(run_id):
            raise ValueError("Unsafe snapshot path segment")
        self.started_at = datetime.now(UTC)
        directory = (
            Path(root).expanduser().resolve()
            / source_id
            / self.started_at.strftime("%Y/%m/%d")
            / run_id
        )
        directory.mkdir(parents=True, exist_ok=False)
        self.final_path = directory / "records.ndjson"
        self.partial_path = directory / "records.ndjson.partial"
        self.manifest_path = directory / "manifest.json"
        self._stream = self.partial_path.open("xb")
        self._digest = hashlib.sha256()
        self._columns: set[str] = set()
        self._bytes = 0
        self._rows = 0
        self._pages = 0
        self._closed = False
        self.source_id = source_id
        self.run_id = run_id
        self.source_url = source_url
        self.dataset_id = dataset_id
        self.query = query
        self.publication = publication or {}

    def append_page(self, rows: list[dict[str, Any]]) -> None:
        if self._closed:
            raise RuntimeError("Snapshot is already closed")
        self._pages += 1
        for row in rows:
            self._columns.update(str(key) for key in row)
            encoded = (
                json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            self._stream.write(encoded)
            self._digest.update(encoded)
            self._bytes += len(encoded)
            self._rows += 1

    def finalize(self, *, extra: dict[str, Any] | None = None) -> SnapshotArtifact:
        if self._closed:
            raise RuntimeError("Snapshot is already closed")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        os.replace(self.partial_path, self.final_path)
        self._closed = True
        retrieved_at = datetime.now(UTC)
        columns = sorted(self._columns)
        schema_sha256 = hashlib.sha256(
            json.dumps(columns, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest: dict[str, Any] = {
            "manifest_version": "1.0",
            "immutability_key": self.run_id,
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "source_url": self.source_url,
            "retrieval_started_at": self.started_at.isoformat(),
            "retrieved_at": retrieved_at.isoformat(),
            "media_type": "application/x-ndjson",
            "content_bytes": self._bytes,
            "row_count": self._rows,
            "page_count": self._pages,
            "content_sha256": self._digest.hexdigest(),
            "schema_columns": columns,
            "schema_sha256": schema_sha256,
            "query": self.query,
            "publication": self.publication,
        }
        if extra:
            manifest.update(extra)
        temporary_manifest = self.manifest_path.with_suffix(".json.partial")
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_manifest, self.manifest_path)
        return SnapshotArtifact(
            object_path=str(self.final_path),
            manifest_path=str(self.manifest_path),
            content_bytes=self._bytes,
            row_count=self._rows,
            page_count=self._pages,
            sha256=self._digest.hexdigest(),
            schema_sha256=schema_sha256,
            retrieved_at=retrieved_at,
            manifest=manifest,
            media_type="application/x-ndjson",
        )

    def abort(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True
        self.partial_path.unlink(missing_ok=True)


class RawFileSnapshotWriter:
    """Stream an official binary publication into the immutable snapshot store."""

    def __init__(
        self,
        *,
        root: str | Path,
        source_id: str,
        run_id: str,
        source_url: str,
        media_type: str,
        filename: str = "source.zip",
        query: dict[str, Any] | None = None,
        publication: dict[str, Any] | None = None,
    ) -> None:
        if not _SAFE_SEGMENT.fullmatch(source_id) or not _SAFE_SEGMENT.fullmatch(run_id):
            raise ValueError("Unsafe snapshot path segment")
        if not _SAFE_SEGMENT.fullmatch(filename):
            raise ValueError("Unsafe snapshot filename")
        self.started_at = datetime.now(UTC)
        directory = (
            Path(root).expanduser().resolve()
            / source_id
            / self.started_at.strftime("%Y/%m/%d")
            / run_id
        )
        directory.mkdir(parents=True, exist_ok=False)
        self.final_path = directory / filename
        self.partial_path = directory / f"{filename}.partial"
        self.manifest_path = directory / "manifest.json"
        self._stream = self.partial_path.open("xb")
        self._digest = hashlib.sha256()
        self._bytes = 0
        self._chunks = 0
        self._closed = False
        self.source_id = source_id
        self.run_id = run_id
        self.source_url = source_url
        self.media_type = media_type
        self.query = query or {}
        self.publication = publication or {}

    def append_chunk(self, content: bytes) -> None:
        if self._closed:
            raise RuntimeError("Snapshot is already closed")
        if not content:
            return
        self._stream.write(content)
        self._digest.update(content)
        self._bytes += len(content)
        self._chunks += 1

    def staging_path(self) -> Path:
        """Flush bytes so a versioned parser can inspect them before publication."""
        if self._closed:
            raise RuntimeError("Snapshot is already closed")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        return self.partial_path

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def content_bytes(self) -> int:
        return self._bytes

    def finalize(
        self,
        *,
        row_count: int,
        schema_descriptor: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> SnapshotArtifact:
        if self._closed:
            raise RuntimeError("Snapshot is already closed")
        self.staging_path()
        self._stream.close()
        os.replace(self.partial_path, self.final_path)
        self._closed = True
        retrieved_at = datetime.now(UTC)
        serialized_schema = json.dumps(
            schema_descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        schema_sha256 = hashlib.sha256(serialized_schema.encode("utf-8")).hexdigest()
        manifest: dict[str, Any] = {
            "manifest_version": "1.0",
            "immutability_key": self.run_id,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "retrieval_started_at": self.started_at.isoformat(),
            "retrieved_at": retrieved_at.isoformat(),
            "media_type": self.media_type,
            "content_bytes": self._bytes,
            "row_count": row_count,
            "chunk_count": self._chunks,
            "content_sha256": self.sha256,
            "schema": schema_descriptor,
            "schema_sha256": schema_sha256,
            "query": self.query,
            "publication": self.publication,
        }
        if extra:
            manifest.update(extra)
        temporary_manifest = self.manifest_path.with_suffix(".json.partial")
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_manifest, self.manifest_path)
        return SnapshotArtifact(
            object_path=str(self.final_path),
            manifest_path=str(self.manifest_path),
            content_bytes=self._bytes,
            row_count=row_count,
            page_count=self._chunks,
            sha256=self.sha256,
            schema_sha256=schema_sha256,
            retrieved_at=retrieved_at,
            manifest=manifest,
            media_type=self.media_type,
        )

    def abort(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True
        self.partial_path.unlink(missing_ok=True)
