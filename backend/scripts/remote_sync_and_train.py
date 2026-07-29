#!/usr/bin/env python3
"""Orquestador remoto PRORA: sync + train con re-login, checkpoints y reanudación.

Variables de entorno principales:
  PRORA_API_BASE, PRORA_OPERATOR_EMAIL, PRORA_OPERATOR_PASSWORD

Modos:
  PRORA_SYNC_ONLY=1     solo ingesta
  PRORA_TRAIN_ONLY=1    solo entrenamiento (recomendado primero)

Entrenamiento seguro:
  PRORA_CHECKPOINT_FILE   ruta del progreso (default ~/.prora/train-checkpoint.json)
  PRORA_RESUME=1          omitir enfermedades ya marcadas OK en el checkpoint
  PRORA_SKIP_TRAINED=1    omitir enfermedades que ya tienen modelo en el portfolio
  PRORA_TRAIN_HORIZONS=4  default solo h4 en Render free
  PRORA_POLL_SECONDS=30   intervalo entre consultas (menos CPU local)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = os.environ.get("PRORA_API_BASE", "https://prora-api.onrender.com/api/v1").rstrip("/")
EMAIL = os.environ.get("PRORA_OPERATOR_EMAIL", "")
PASSWORD = os.environ.get("PRORA_OPERATOR_PASSWORD", "")
CHECKPOINT_FILE = Path(
    os.environ.get("PRORA_CHECKPOINT_FILE", Path.home() / ".prora" / "train-checkpoint.json")
)
POLL_SECONDS = max(10, int(os.environ.get("PRORA_POLL_SECONDS", "30")))

SYNC_SOURCES: list[str] = [
    "dane-divipola",
    "dane-socioeconomic",
    "pai-municipal-2026",
    "pai-municipal-history",
    "sivigila-bucaramanga-dengue",
    "sivigila-bucaramanga-events",
    "sivigila-bucaramanga-ira",
    "sivigila-boyaca-events",
    "sivigila-caqueta-dengue",
    "sivigila-casanare-dengue",
    "sivigila-pereira-dengue",
    "sivigila-tulua-dengue",
    "sivigila-santa-rosa-cabal-events",
    "sivigila-microdata-2024",
    "sivigila-national",
    "ins-bes-weekly",
    "ideam-stations",
    "ideam-precipitation",
    "ideam-temperature",
    "ideam-humidity",
    "pai-national",
    "pai-valle-municipal",
    "ins-irca-water-quality",
    # Federación al final: bloquea la API mucho tiempo.
    "sivigila-territorial-open",
]

SIVIGILA_NATIONAL_WINDOWS: list[tuple[str, str]] = [
    ("2007-01-01", "2009-01-01"),
    ("2009-01-01", "2011-01-01"),
    ("2011-01-01", "2013-01-01"),
    ("2013-01-01", "2015-01-01"),
    ("2015-01-01", "2017-01-01"),
    ("2017-01-01", "2019-01-01"),
    ("2019-01-01", "2021-01-01"),
    ("2021-01-01", "2023-01-01"),
]

# Pequeñas primero: validan el pipeline sin tumbar Render.
TRAIN_ORDER = ("ira", "leishmaniasis", "malaria", "dengue", "chikunguna", "zika")


def _log(message: str) -> None:
    print(message, flush=True)


class ApiClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._token_at = 0.0

    def login(self) -> str:
        if not EMAIL or not PASSWORD:
            raise SystemExit("Defina PRORA_OPERATOR_EMAIL y PRORA_OPERATOR_PASSWORD")
        code, payload = self._raw_request(
            "POST",
            "/auth/login",
            body={"email": EMAIL, "password": PASSWORD},
            timeout=180,
        )
        if code != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise SystemExit(f"login falló ({code}): {payload}")
        self._token = str(payload["access_token"])
        self._token_at = time.time()
        return self._token

    def token(self) -> str:
        # JWT expira ~15 min; renovar antes.
        if self._token is None or time.time() - self._token_at > 600:
            return self.login()
        return self._token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> tuple[int, Any]:
        code, payload = self._raw_request(method, path, token=self.token(), body=body, timeout=timeout)
        if code == 401:
            _log("  token expirado → re-login")
            self.login()
            code, payload = self._raw_request(method, path, token=self.token(), body=body, timeout=timeout)
        return code, payload

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> tuple[int, Any]:
        url = f"{API_BASE}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return exc.code, payload


def _load_checkpoint() -> dict[str, Any]:
    if os.environ.get("PRORA_RESUME") != "1" or not CHECKPOINT_FILE.exists():
        return {"completed_trains": {}, "completed_syncs": []}
    try:
        return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"completed_trains": {}, "completed_syncs": []}


def _save_checkpoint(state: dict[str, Any]) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _wait_run(api: ApiClient, run_id: str, *, timeout_s: int = 7200) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, runs = api.request("GET", "/sources/runs?limit=120")
        if code == 200 and isinstance(runs, list):
            match = next((item for item in runs if item.get("id") == run_id), None)
            if match and match.get("status") not in {"pending", "running"}:
                return match
        time.sleep(POLL_SECONDS)
    return {"status": "timeout", "error_message": f"timeout esperando run {run_id}"}


def _wait_train(api: ApiClient, job_id: str, *, timeout_s: int = 7200) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, job = api.request("GET", f"/models/train/{job_id}")
        if code == 200 and isinstance(job, dict) and job.get("status") not in {"pending", "running"}:
            return job
        time.sleep(POLL_SECONDS)
    return {"status": "timeout", "error_message": f"timeout esperando train {job_id}"}


def _portfolio_trained(api: ApiClient) -> dict[str, int]:
    code, portfolio = api.request("GET", "/models/readiness/portfolio")
    if code != 200 or not isinstance(portfolio, dict):
        return {}
    result: dict[str, int] = {}
    for item in portfolio.get("diseases", []):
        disease = str(item.get("disease", ""))
        trained = sum(1 for model in item.get("models", []) if model.get("state") == "trained")
        result[disease] = trained
    return result


def _enqueue_sync(api: ApiClient, source_id: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    code, payload = api.request("POST", f"/sources/{source_id}/sync", body=body or {})
    if code == 409:
        _log(f"  SKIP/BUSY {source_id}")
        return None
    if code not in {200, 202} or not isinstance(payload, dict):
        _log(f"  FAIL enqueue {source_id} ({code}): {payload}")
        return None
    return payload


def sync_one(api: ApiClient, source_id: str, body: dict[str, Any] | None = None) -> str:
    _log(f"SYNC {source_id}")
    payload = _enqueue_sync(api, source_id, body)
    if payload is None:
        return "skipped"
    run_id = payload["id"]
    _log(f"  RUN {run_id}")
    finished = _wait_run(api, run_id)
    status = str(finished.get("status"))
    _log(
        f"  DONE {source_id} status={status} "
        f"accepted={finished.get('rows_accepted')} rejected={finished.get('rows_rejected')} "
        f"err={finished.get('error_message')}"
    )
    return status


def sync_all(api: ApiClient, checkpoint: dict[str, Any]) -> None:
    skip_slow = os.environ.get("PRORA_SKIP_SLOW") == "1"
    completed = set(checkpoint.get("completed_syncs", []))
    for source_id in SYNC_SOURCES:
        if source_id in completed and os.environ.get("PRORA_RESUME") == "1":
            _log(f"SKIP {source_id} (checkpoint)")
            continue
        if source_id == "sivigila-national":
            if skip_slow:
                _log("SKIP sivigila-national (PRORA_SKIP_SLOW=1)")
                continue
            for start, end in SIVIGILA_NATIONAL_WINDOWS:
                label = f"{start[:4]}–{int(end[:4]) - 1}"
                _log(f"SYNC sivigila-national chunk {label}")
                payload = _enqueue_sync(
                    api,
                    "sivigila-national",
                    {"mode": "backfill", "from_date": start, "to_date": end},
                )
                if payload is None:
                    continue
                finished = _wait_run(api, payload["id"])
                _log(f"  chunk {label} → {finished.get('status')}")
            checkpoint.setdefault("completed_syncs", []).append("sivigila-national")
            _save_checkpoint(checkpoint)
            continue
        if skip_slow and source_id == "sivigila-microdata-2024":
            _log("SKIP sivigila-microdata-2024")
            continue
        status = sync_one(api, source_id)
        if status in {"succeeded", "partial"}:
            checkpoint.setdefault("completed_syncs", []).append(source_id)
            _save_checkpoint(checkpoint)


def train_all(api: ApiClient, checkpoint: dict[str, Any]) -> None:
    force = os.environ.get("PRORA_FORCE_TRAIN") == "1"
    skip_trained = os.environ.get("PRORA_SKIP_TRAINED") == "1"
    horizon_raw = os.environ.get("PRORA_TRAIN_HORIZONS", "4")
    horizons = sorted({int(item.strip()) for item in horizon_raw.split(",") if item.strip()})
    disease_raw = os.environ.get("PRORA_DISEASES")
    diseases = (
        tuple(item.strip() for item in disease_raw.split(",") if item.strip())
        if disease_raw
        else TRAIN_ORDER
    )
    trained_map = _portfolio_trained(api) if skip_trained else {}
    completed = checkpoint.setdefault("completed_trains", {})

    for disease in diseases:
        if os.environ.get("PRORA_RESUME") == "1" and completed.get(disease) == "succeeded":
            _log(f"SKIP train {disease} (checkpoint OK)")
            continue
        if skip_trained and trained_map.get(disease, 0) >= len(horizons):
            _log(f"SKIP train {disease} (ya entrenado en API: {trained_map[disease]}/{len(horizons)})")
            completed[disease] = "succeeded"
            _save_checkpoint(checkpoint)
            continue

        _log(f"TRAIN {disease} horizons={horizons} force={force}")
        code, payload = api.request(
            "POST",
            "/models/train",
            body={"disease": disease, "horizons": horizons, "force": force},
        )
        if code not in {200, 202} or not isinstance(payload, dict):
            _log(f"  FAIL enqueue ({code}): {payload}")
            completed[disease] = "enqueue_failed"
            _save_checkpoint(checkpoint)
            continue

        job_id = str(payload.get("job_id") or payload.get("id") or "")
        if not job_id:
            completed[disease] = "no_job_id"
            _save_checkpoint(checkpoint)
            continue

        _log(f"  JOB {job_id}")
        finished = _wait_train(api, job_id)
        status = str(finished.get("status"))
        result = finished.get("result") if isinstance(finished.get("result"), dict) else {}
        _log(
            f"  DONE {disease} status={status} "
            f"forecasts={result.get('forecasts_created')} "
            f"eligible={result.get('forecasts_operationally_eligible')} "
            f"err={finished.get('error_message')}"
        )
        completed[disease] = status
        _save_checkpoint(checkpoint)

        if status != "succeeded":
            _log(f"  ⚠ {disease} no terminó OK; puedes reanudar con PRORA_RESUME=1")


def verify(api: ApiClient) -> None:
    trained_map = _portfolio_trained(api)
    _log("\n=== VALIDACIÓN ===")
    for disease in TRAIN_ORDER:
        count = trained_map.get(disease, 0)
        _log(f"  {disease}: modelos entrenados = {count}/2")

    code, portfolio = api.request("GET", "/models/readiness/portfolio")
    if isinstance(portfolio, dict):
        for item in portfolio.get("diseases", []):
            disease = item.get("disease")
            if disease not in ("dengue", "ira", "malaria", "leishmaniasis"):
                continue
            models = item.get("models", [])
            for model in models:
                if model.get("state") != "trained":
                    continue
                validation = model.get("validation", {})
                mae = validation.get("temporal_mae")
                benchmark = validation.get("benchmark_available")
                _log(
                    f"  H{model.get('horizon')} {disease}: "
                    f"MAE={mae} benchmark={benchmark} version={model.get('version')}"
                )

    for disease in ("ira", "dengue"):
        code, items = api.request("GET", f"/risk/map?disease={disease}&horizon=4")
        count = len(items) if isinstance(items, list) else 0
        _log(f"  mapa {disease} h4 → {count} territorios con predicción")


def main() -> None:
    _log(f"API {API_BASE}")
    _log(f"Checkpoint: {CHECKPOINT_FILE} | poll={POLL_SECONDS}s")
    api = ApiClient()
    api.login()
    _log("login OK")

    checkpoint = _load_checkpoint()
    sync_only = os.environ.get("PRORA_SYNC_ONLY") == "1"
    train_only = os.environ.get("PRORA_TRAIN_ONLY") == "1"
    verify_only = os.environ.get("PRORA_VERIFY_ONLY") == "1"

    if verify_only:
        verify(api)
        return

    if not train_only:
        sync_all(api, checkpoint)
    if not sync_only:
        train_all(api, checkpoint)
    verify(api)
    _log(f"\nProgreso guardado en {CHECKPOINT_FILE}")


if __name__ == "__main__":
    main()
