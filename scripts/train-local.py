#!/usr/bin/env python3
"""Entrena modelos PRORA en tu CPU local conectándose a la BD de Render.

Uso:
  # Entrenar una enfermedad:
  PRORA_DATABASE_URL='postgres://...' python3 scripts/train-local.py --disease ira

  # Entrenar todas las disponibles:
  PRORA_DATABASE_URL='postgres://...' python3 scripts/train-local.py --all

  # Solo validar artefactos existentes:
  python3 scripts/train-local.py --verify

Requisitos:
  pip install asyncpg sqlalchemy[asyncio] pandas scikit-learn joblib numpy

La DATABASE_URL se obtiene del dashboard de Render → prora-db → External Connection String.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train-local")

DISEASES = ("ira", "leishmaniasis", "malaria", "dengue")
REGISTRY_PATH = ROOT / "artifacts" / "models"


def _get_database_url() -> str:
    url = os.environ.get("PRORA_DATABASE_URL", "")
    if not url:
        print(
            "ERROR: Falta PRORA_DATABASE_URL.\n"
            "  Ve al dashboard de Render → prora-db → External Connection String\n"
            "  y expórtala:\n"
            "    export PRORA_DATABASE_URL='postgresql://user:pass@host/db'\n"
        )
        sys.exit(1)
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


async def _build_panel(db_url: str, disease: str):
    """Conecta a la BD remota y construye el panel de entrenamiento."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    ssl_args = {"ssl": True} if "render.com" in db_url or "neon" in db_url else {}
    engine = create_async_engine(db_url, connect_args=ssl_args, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from app.jobs.dataset import build_training_dataset

    async with factory() as session:
        dataset = await build_training_dataset(session, disease)

    await engine.dispose()
    return dataset


def _train_disease(panel_frame, disease: str, horizon: int = 4):
    """Entrena un modelo local y lo registra en el filesystem."""
    from app.ml.models import train_model
    from app.ml.config import MLConfig
    from app.ml.registry import ModelRegistry

    cfg = MLConfig()

    log.info(f"Entrenando {disease} h={horizon} ({len(panel_frame)} filas)...")
    t0 = time.time()
    bundle = train_model(panel_frame, disease, horizon, cfg)
    elapsed = time.time() - t0
    log.info(f"  Entrenado en {elapsed:.1f}s")

    registry = ModelRegistry(REGISTRY_PATH)
    version = registry.register(bundle, activate=True)
    log.info(f"  Registrado: {disease}/h{horizon}/{version}")
    log.info(f"  MAE={bundle.metrics.get('mae', '?'):.2f}")

    benchmark = bundle.metrics.get("benchmark", {})
    log.info(f"  Benchmark: {json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in benchmark.items()}, indent=2)}")

    return version, bundle.metrics


def _verify():
    """Verifica artefactos locales."""
    from app.ml.registry import ModelRegistry

    registry = ModelRegistry(REGISTRY_PATH)
    log.info("=== VERIFICACIÓN DE MODELOS LOCALES ===")
    found = 0
    for disease in DISEASES:
        for horizon in (4,):
            latest = registry.latest_version(disease, horizon)
            if latest:
                found += 1
                try:
                    result = registry.verify(disease, horizon, latest)
                    manifest = result["manifest"]
                    log.info(
                        f"  {disease}/h{horizon}: {latest} ✓ "
                        f"MAE={manifest.get('metrics', {}).get('mae', '?')} "
                        f"rows={manifest.get('training_rows', '?')}"
                    )
                except Exception as e:
                    log.error(f"  {disease}/h{horizon}: {latest} CORRUPTO: {e}")
            else:
                log.info(f"  {disease}/h{horizon}: sin modelo")
    if not found:
        log.info("  No hay modelos entrenados. Corre con --disease o --all primero.")


async def _train_one(db_url: str, disease: str):
    log.info(f"=== {disease.upper()} ===")
    log.info("Descargando panel desde BD remota...")
    t0 = time.time()
    dataset = await _build_panel(db_url, disease)
    elapsed = time.time() - t0
    frame = dataset.frame
    log.info(f"  Panel: {len(frame)} filas, fingerprint={dataset.fingerprint[:12]}... ({elapsed:.1f}s)")

    if len(frame) < 50:
        log.warning(f"  SKIP {disease}: solo {len(frame)} filas (mínimo 50)")
        return

    version, metrics = _train_disease(frame, disease, horizon=4)
    log.info(f"  {disease} COMPLETADO: {version}\n")


async def main():
    parser = argparse.ArgumentParser(description="Entrenar modelos PRORA localmente")
    parser.add_argument("--disease", type=str, help="Enfermedad a entrenar")
    parser.add_argument("--all", action="store_true", help="Entrenar todas las disponibles")
    parser.add_argument("--verify", action="store_true", help="Solo verificar artefactos")
    args = parser.parse_args()

    if args.verify:
        _verify()
        return

    if not args.disease and not args.all:
        parser.print_help()
        print("\nEjemplos:")
        print("  PRORA_DATABASE_URL='...' python3 scripts/train-local.py --disease ira")
        print("  PRORA_DATABASE_URL='...' python3 scripts/train-local.py --all")
        print("  python3 scripts/train-local.py --verify")
        return

    db_url = _get_database_url()
    diseases = DISEASES if args.all else (args.disease,)

    results = {}
    for disease in diseases:
        try:
            await _train_one(db_url, disease)
            results[disease] = "OK"
        except Exception as e:
            log.error(f"  FALLO {disease}: {e}")
            results[disease] = f"FALLO: {e}"

    log.info("\n=== RESUMEN ===")
    for disease, status in results.items():
        log.info(f"  {disease}: {status}")

    _verify()


if __name__ == "__main__":
    asyncio.run(main())
