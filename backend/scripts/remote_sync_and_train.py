#!/usr/bin/env python3
"""Orchestrate remote sync + train against a deployed PRORA API (e.g. Render).

Requires:
  PRORA_API_BASE   e.g. https://prora-api.onrender.com/api/v1
  PRORA_OPERATOR_EMAIL
  PRORA_OPERATOR_PASSWORD

Optional:
  PRORA_SYNC_ONLY=1        skip training
  PRORA_TRAIN_ONLY=1       skip sync
  PRORA_FORCE_TRAIN=1      force retrain even if fingerprint matches
  PRORA_SKIP_SLOW=1        skip microdata 2024 and chunked national backfill
  PRORA_TRAIN_HORIZONS=4   comma list, default 4 (solo h4 en Render free)
  PRORA_DISEASES=ira,dengue  subset; default ira,leishmaniasis,malaria,dengue
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Any

API_BASE = os.environ.get("PRORA_API_BASE", "https://prora-api.onrender.com/api/v1").rstrip("/")
EMAIL = os.environ.get("PRORA_OPERATOR_EMAIL", "")
PASSWORD = os.environ.get("PRORA_OPERATOR_PASSWORD", "")

# Prerrequisitos → epidemiología reciente → covariables → referencia 2026.
SYNC_SOURCES: list[str] = [
    "dane-divipola",
    "dane-socioeconomic",
    "sivigila-territorial-open",
    "sivigila-bucaramanga-dengue",
    "sivigila-bucaramanga-events",
    "sivigila-bucaramanga-ira",
    "sivigila-boyaca-events",
    "sivigila-caqueta-dengue",
    "sivigila-casanare-dengue",
    "sivigila-pereira-dengue",
    "sivigila-tulua-dengue",
    "sivigila-santa-rosa-cabal-events",
    "pai-municipal-2026",
    "pai-municipal-history",
    "sivigila-microdata-2024",
    "sivigila-national",
    "ideam-stations",
    "ideam-precipitation",
    "ideam-temperature",
    "ideam-humidity",
    "ins-bes-weekly",
    "pai-national",
    "pai-valle-municipal",
    "ins-irca-water-quality",
]

# SIVIGILA agregado nacional: ventanas cortas evitan timeouts en Render free.
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

DISEASES = ("ira", "leishmaniasis", "malaria", "dengue", "chikunguna", "zika")


def _log(message: str) -> None:
    print(message, flush=True)


def _request(
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


def _login() -> str:
    if not EMAIL or not PASSWORD:
        raise SystemExit("Defina PRORA_OPERATOR_EMAIL y PRORA_OPERATOR_PASSWORD")
    code, payload = _request(
        "POST",
        "/auth/login",
        body={"email": EMAIL, "password": PASSWORD},
        timeout=180,
    )
    if code != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise SystemExit(f"login falló ({code}): {payload}")
    return str(payload["access_token"])


def _wait_run(token: str, run_id: str, *, timeout_s: int = 5400) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, runs = _request("GET", "/sources/runs?limit=120", token=token, timeout=120)
        if code == 200 and isinstance(runs, list):
            match = next((item for item in runs if item.get("id") == run_id), None)
            if match and match.get("status") not in {"pending", "running"}:
                return match
        time.sleep(12)
    raise SystemExit(f"timeout esperando run {run_id}")


def _wait_train(token: str, job_id: str, *, timeout_s: int = 7200) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, job = _request("GET", f"/models/train/{job_id}", token=token, timeout=120)
        if code == 200 and isinstance(job, dict) and job.get("status") not in {
            "pending",
            "running",
        }:
            return job
        time.sleep(15)
    raise SystemExit(f"timeout esperando train {job_id}")


def _enqueue_sync(
    token: str,
    source_id: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    code, payload = _request(
        "POST",
        f"/sources/{source_id}/sync",
        token=token,
        body=body or {},
        timeout=180,
    )
    if code == 409:
        detail = payload.get("error", payload) if isinstance(payload, dict) else payload
        print(f"  SKIP/BUSY {source_id}: {detail}")
        return None
    if code not in {200, 202} or not isinstance(payload, dict):
        print(f"  FAIL enqueue {source_id} ({code}): {payload}")
        return None
    return payload


def sync_one(token: str, source_id: str, body: dict[str, Any] | None = None) -> None:
    print(f"SYNC enqueue {source_id}", flush=True)
    payload = _enqueue_sync(token, source_id, body)
    if payload is None:
        return
    run_id = payload["id"]
    print(f"  RUN {run_id}")
    finished = _wait_run(token, run_id)
    print(
        f"  DONE {source_id} status={finished.get('status')} "
        f"accepted={finished.get('rows_accepted')} "
        f"rejected={finished.get('rows_rejected')} "
        f"err={finished.get('error_message')}"
    )


def sync_sivigila_national_by_years(token: str) -> None:
    print("SYNC sivigila-national (ventanas anuales 2007–2022)")
    for start, end in SIVIGILA_NATIONAL_WINDOWS:
        label = f"{start[:4]}–{int(end[:4]) - 1}"
        print(f"  chunk {label}")
        payload = _enqueue_sync(
            token,
            "sivigila-national",
            {
                "mode": "backfill",
                "from_date": start,
                "to_date": end,
            },
        )
        if payload is None:
            continue
        run_id = payload["id"]
        finished = _wait_run(token, run_id, timeout_s=7200)
        print(
            f"  DONE chunk {label} status={finished.get('status')} "
            f"accepted={finished.get('rows_accepted')} rejected={finished.get('rows_rejected')}"
        )


def sync_all(token: str) -> None:
    skip_slow = os.environ.get("PRORA_SKIP_SLOW") == "1"
    for source_id in SYNC_SOURCES:
        if source_id == "sivigila-national":
            if skip_slow:
                print("SKIP sivigila-national (PRORA_SKIP_SLOW=1)")
                continue
            sync_sivigila_national_by_years(token)
            continue
        if skip_slow and source_id == "sivigila-microdata-2024":
            print("SKIP sivigila-microdata-2024 (PRORA_SKIP_SLOW=1)")
            continue
        sync_one(token, source_id)


def train_all(token: str) -> None:
    force = os.environ.get("PRORA_FORCE_TRAIN") == "1"
    horizon_raw = os.environ.get("PRORA_TRAIN_HORIZONS", "4")
    horizons = sorted({int(item.strip()) for item in horizon_raw.split(",") if item.strip()})
    disease_raw = os.environ.get("PRORA_DISEASES")
    diseases = (
        tuple(item.strip() for item in disease_raw.split(",") if item.strip())
        if disease_raw
        else DISEASES
    )
    for disease in diseases:
        print(f"TRAIN enqueue {disease} horizons={horizons} force={force}")
        code, payload = _request(
            "POST",
            "/models/train",
            token=token,
            body={"disease": disease, "horizons": horizons, "force": force},
            timeout=180,
        )
        if code not in {200, 202} or not isinstance(payload, dict):
            print(f"  FAIL enqueue {disease} ({code}): {payload}")
            continue
        job_id = payload.get("job_id") or payload.get("id")
        print(f"  JOB {job_id}")
        if not job_id:
            continue
        finished = _wait_train(token, str(job_id))
        result = finished.get("result") if isinstance(finished.get("result"), dict) else {}
        print(
            f"  DONE {disease} status={finished.get('status')} "
            f"forecasts={result.get('forecasts_created')} "
            f"eligible={result.get('forecasts_operationally_eligible')} "
            f"err={finished.get('error_message')}"
        )


def verify(token: str) -> int:
    """Return non-zero if portfolio/readiness looks empty after pipeline."""
    issues = 0
    code, portfolio = _request("GET", "/models/readiness/portfolio", token=token, timeout=180)
    print("\n=== PORTFOLIO ===", code)
    if isinstance(portfolio, dict):
        for item in portfolio.get("diseases", []):
            disease = item.get("disease")
            trained = sum(1 for model in item.get("models", []) if model.get("state") == "trained")
            rows = item.get("data", {}).get("observed_rows", 0)
            week_end = item.get("data", {}).get("week_end")
            print(f"  {disease}: rows={rows} week_end={week_end} trained={trained}/2")
            if rows < 500:
                issues += 1
        print(json.dumps(portfolio, ensure_ascii=False, indent=2)[:2500])
    else:
        issues += 1
        print(portfolio)

    for disease in ("dengue", "ira"):
        code, alerts = _request(
            "GET",
            f"/risk/alerts?disease={disease}&limit=5",
            token=token,
            timeout=120,
        )
        count = len(alerts) if isinstance(alerts, list) else 0
        print(f"\n=== ALERTS {disease} === {code} count={count}")
        code, items = _request("GET", f"/risk/map?disease={disease}&horizon=4", token=token, timeout=120)
        map_count = len(items) if isinstance(items, list) else 0
        print(f"=== MAP {disease} h4 === {code} territories={map_count}")

    return issues


def main() -> None:
    _log(f"API {API_BASE}")
    token = _login()
    _log("login OK")
    sync_only = os.environ.get("PRORA_SYNC_ONLY") == "1"
    train_only = os.environ.get("PRORA_TRAIN_ONLY") == "1"
    if not train_only:
        sync_all(token)
    if not sync_only:
        train_all(token)
    issues = verify(token)
    if issues:
        print(f"\nVerificación: {issues} enfermedades con datos insuficientes (<500 filas).")
    sys.exit(0 if issues <= 2 else 1)


if __name__ == "__main__":
    main()
