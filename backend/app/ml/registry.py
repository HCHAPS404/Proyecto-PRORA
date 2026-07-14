"""Filesystem-backed, versioned model registry."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib

from .models import ModelBundle


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-.")
    if not segment:
        raise ValueError("Registry path segment is empty or unsafe")
    return segment


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"Cannot JSON serialize {type(value).__name__}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


class ModelRegistry:
    """Persist immutable model versions and an atomic latest pointer."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def register(
        self,
        bundle: ModelBundle,
        *,
        version: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
        activate: bool = True,
    ) -> str:
        disease = _safe_segment(bundle.disease)
        horizon = f"h{int(bundle.horizon)}"
        generated = datetime.now(UTC).strftime("v%Y%m%dT%H%M%SZ") + f"-{uuid4().hex[:8]}"
        version_key = _safe_segment(version or generated)
        target = self.root / disease / horizon / version_key
        target.mkdir(parents=True, exist_ok=False)

        artifact = target / "model.joblib"
        artifact_tmp = target / ".model.joblib.tmp"
        joblib.dump(bundle, artifact_tmp, compress=3)
        os.replace(artifact_tmp, artifact)
        artifact_hash = _sha256(artifact)
        manifest = {
            "schema_version": 2,
            "version": version_key,
            "disease": bundle.disease,
            "horizon": bundle.horizon,
            "trained_at": bundle.trained_at,
            "training_rows": bundle.training_rows,
            "training_start": bundle.training_start,
            "training_end": bundle.training_end,
            "feature_count": len(bundle.feature_names),
            "features": bundle.feature_names,
            "metrics": bundle.metrics,
            "fold_metrics": bundle.fold_metrics,
            "config": bundle.config,
            "outbreak_threshold": bundle.outbreak_threshold,
            "conformal_radius": bundle.conformal_radius,
            "temporal_backend": bundle.model.temporal_backend,
            "artifact_sha256": artifact_hash,
            "runtime": {
                "python": platform.python_version(),
                "numpy": _dependency_version("numpy"),
                "pandas": _dependency_version("pandas"),
                "scikit_learn": _dependency_version("scikit-learn"),
                "joblib": _dependency_version("joblib"),
                "torch": _dependency_version("torch"),
            },
            **(extra_metadata or {}),
        }
        self._write_json_atomic(target / "manifest.json", manifest)
        if activate:
            self.activate(disease, bundle.horizon, version_key)
        return version_key

    def activate(self, disease: str, horizon: int, version: str) -> None:
        """Atomically move the inference pointer after integrity verification."""

        disease_key = _safe_segment(disease)
        version_key = _safe_segment(version)
        self.verify(disease_key, horizon, version_key)
        self._write_json_atomic(
            self.root / disease_key / f"h{int(horizon)}" / "latest.json",
            {"version": version_key, "updated_at": datetime.now(UTC).isoformat()},
        )

    def latest_version(self, disease: str, horizon: int) -> str | None:
        pointer = self.root / _safe_segment(disease) / f"h{int(horizon)}" / "latest.json"
        if not pointer.exists():
            return None
        return str(json.loads(pointer.read_text(encoding="utf-8"))["version"])

    def clear_latest(self, disease: str, horizon: int, *, expected: str | None = None) -> None:
        """Remove a pointer only when it still targets an uncommitted candidate."""

        pointer = self.root / _safe_segment(disease) / f"h{int(horizon)}" / "latest.json"
        if not pointer.exists():
            return
        current = str(json.loads(pointer.read_text(encoding="utf-8"))["version"])
        if expected is None or current == expected:
            pointer.unlink()

    def restore_latest(
        self,
        disease: str,
        horizon: int,
        previous: str | None,
        *,
        expected_current: str,
    ) -> bool:
        """Compensate a failed DB promotion without overwriting a newer pointer.

        Callers coordinate this compare-and-set with the model-promotion DB lock
        in multi-process deployments.
        """

        if self.latest_version(disease, horizon) != expected_current:
            return False
        if previous:
            self.activate(disease, horizon, previous)
        else:
            self.clear_latest(disease, horizon, expected=expected_current)
        return True

    def verify(self, disease: str, horizon: int, version: str) -> dict[str, Any]:
        """Verify the artifact against its immutable manifest without loading it."""

        base = self.root / _safe_segment(disease) / f"h{int(horizon)}" / _safe_segment(version)
        artifact = base / "model.joblib"
        manifest_path = base / "manifest.json"
        if not artifact.exists() or not manifest_path.exists():
            raise FileNotFoundError(f"Incomplete model version: {base}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_hash = str(manifest.get("artifact_sha256", ""))
        actual_hash = _sha256(artifact)
        if not expected_hash or actual_hash != expected_hash:
            raise OSError(f"Model artifact checksum mismatch: {artifact}")
        return {"valid": True, "artifact_sha256": actual_hash, "manifest": manifest}

    def load(self, disease: str, horizon: int, version: str | None = None) -> ModelBundle:
        bundle, _ = self.load_with_manifest(disease, horizon, version)
        return bundle

    def load_with_manifest(
        self,
        disease: str,
        horizon: int,
        version: str | None = None,
    ) -> tuple[ModelBundle, dict[str, Any]]:
        """Verify once, then deserialize an artifact with its exact manifest."""

        base = self.root / _safe_segment(disease) / f"h{int(horizon)}"
        if version is None:
            pointer = base / "latest.json"
            if not pointer.exists():
                raise FileNotFoundError(f"No registered model for {disease} at h={horizon}")
            version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
        artifact = base / _safe_segment(version) / "model.joblib"
        verification = self.verify(disease, horizon, version)
        bundle = joblib.load(artifact)
        if not isinstance(bundle, ModelBundle):
            raise TypeError("Registry artifact is not a PRORA ModelBundle")
        return bundle, verification["manifest"]

    def manifest(self, disease: str, horizon: int, version: str | None = None) -> dict[str, Any]:
        base = self.root / _safe_segment(disease) / f"h{int(horizon)}"
        if version is None:
            pointer = base / "latest.json"
            if not pointer.exists():
                raise FileNotFoundError(f"No registered model for {disease} at h={horizon}")
            version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
        manifest_path = base / _safe_segment(version) / "manifest.json"
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def list_versions(self, disease: str, horizon: int) -> list[dict[str, Any]]:
        base = self.root / _safe_segment(disease) / f"h{int(horizon)}"
        if not base.exists():
            return []
        manifests = []
        for path in sorted(base.glob("*/manifest.json"), reverse=True):
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
        return manifests

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(
                _json_safe(value),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
                default=_json_default,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dependency_version(package: str) -> str | None:
    try:
        return package_version(package)
    except PackageNotFoundError:
        return None
