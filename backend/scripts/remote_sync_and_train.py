#!/usr/bin/env python3
"""Orchestrate remote sync + train against a deployed PRORA API (e.g. Render).

Requires:
  PRORA_API_BASE   e.g. https://prora-api.onrender.com/api/v1
  PRORA_OPERATOR_EMAIL
  PRORA_OPERATOR_PASSWORD

Optional:
  PRORA_SYNC_ONLY=1   skip training
  PRORA_TRAIN_ONLY=1  skip sync
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

API_BASE = os.environ.get("PRORA_API_BASE", "https://prora-api.onrender.com/api/v1").rstrip("/")
EMAIL = os.environ.get("PRORA_OPERATOR_EMAIL", "")
PASSWORD = os.environ.get("PRORA_OPERATOR_PASSWORD", "")

# Orden de valor predictivo (prerrequisitos primero).
SYNC_SOURCES = [
    "dane-divipola",
    "dane-socioeconomic",
    "ideam-stations",
    "ideam-precipitation",
    "ideam-temperature",
    "ideam-humidity",
    "sivigila-national",
    "sivigila-microdata-2024",
    "sivigila-territorial-open",
    "ins-bes-weekly",
    "pai-national",
    "pai-municipal-history",
    "pai-municipal-2026",
    "pai-valle-municipal",
    "ins-irca-water-quality",
]

DISEASES = ("dengue", "malaria", "chikunguna", "zika", "leishmaniasis", "ira")


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


def _wait_run(token: str, run_id: str, *, timeout_s: int = 3600) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, runs = _request("GET", "/sources/runs?limit=80", token=token, timeout=120)
        if code == 200 and isinstance(runs, list):
            match = next((item for item in runs if item.get("id") == run_id), None)
            if match and match.get("status") not in {"pending", "running"}:
                return match
        time.sleep(15)
    raise SystemExit(f"timeout esperando run {run_id}")


def _wait_train(token: str, job_id: str, *, timeout_s: int = 3600) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code, job = _request("GET", f"/models/train/{job_id}", token=token, timeout=120)
        if code == 200 and isinstance(job, dict) and job.get("status") not in {
            "pending",
            "running",
        }:
            return job
        time.sleep(20)
    raise SystemExit(f"timeout esperando train {job_id}")


def sync_all(token: str) -> None:
    for source_id in SYNC_SOURCES:
        print(f"SYNC enqueue {source_id}")
        code, payload = _request(
            "POST",
            f"/sources/{source_id}/sync",
            token=token,
            body={},
            timeout=180,
        )
        if code == 409:
            detail = payload.get("error", payload) if isinstance(payload, dict) else payload
            print(f"  SKIP/BUSY {source_id}: {detail}")
            continue
        if code not in {200, 202} or not isinstance(payload, dict):
            print(f"  FAIL enqueue {source_id} ({code}): {payload}")
            continue
        run_id = payload["id"]
        print(f"  RUN {run_id}")
        finished = _wait_run(token, run_id)
        print(
            f"  DONE {source_id} status={finished.get('status')} "
            f"accepted={finished.get('rows_accepted')} "
            f"rejected={finished.get('rows_rejected')} "
            f"err={finished.get('error_message')}"
        )


def train_all(token: str) -> None:
    for disease in DISEASES:
        print(f"TRAIN enqueue {disease}")
        code, payload = _request(
            "POST",
            "/models/train",
            token=token,
            body={"disease": disease, "horizons": [3, 4], "force": False},
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
        print(
            f"  DONE {disease} status={finished.get('status')} "
            f"err={finished.get('error_message')}"
        )


def main() -> None:
    print(f"API {API_BASE}")
    token = _login()
    print("login OK")
    sync_only = os.environ.get("PRORA_SYNC_ONLY") == "1"
    train_only = os.environ.get("PRORA_TRAIN_ONLY") == "1"
    if not train_only:
        sync_all(token)
    if not sync_only:
        train_all(token)
    code, portfolio = _request("GET", "/models/readiness/portfolio", token=token, timeout=180)
    print("PORTFOLIO", code)
    print(json.dumps(portfolio, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
