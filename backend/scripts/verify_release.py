"""Lightweight release checks that do not require Docker to be installed."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import yaml

REQUIRED_SERVICES = {"db", "migrate", "api", "worker", "frontend"}
REQUIRED_TABLES = {
    "users",
    "municipalities",
    "epidemiological_observations",
    "model_versions",
    "forecasts",
    "alert_events",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()

    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = set(compose.get("services", {}))
    if not REQUIRED_SERVICES <= services:
        raise SystemExit(f"Missing Compose services: {sorted(REQUIRED_SERVICES - services)}")

    with sqlite3.connect(arguments.database) as connection:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type = 'table'")
        }
    if not REQUIRED_TABLES <= tables:
        raise SystemExit(f"Missing migrated tables: {sorted(REQUIRED_TABLES - tables)}")
    print(f"release-check-ok services={len(services)} tables={len(tables)}")


if __name__ == "__main__":
    main()
