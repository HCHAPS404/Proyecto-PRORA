#!/usr/bin/env python3
"""Publica modelos entrenados localmente en la BD de Render.

Inserta ModelVersion, genera Forecasts (con drivers SHAP) y AlertEvents.
Después de esto el dashboard muestra predicciones e interpretaciones.

Uso:
  PRORA_DATABASE_URL='postgres://...' python3 scripts/publish-models.py
  PRORA_DATABASE_URL='postgres://...' python3 scripts/publish-models.py --disease ira
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("publish")

DISEASES = ("ira", "leishmaniasis", "malaria", "dengue")
REGISTRY_PATH = ROOT / "artifacts" / "models"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def _as_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return date.fromisoformat(str(val)[:10])
    except (ValueError, TypeError):
        return None


def _get_database_url() -> str:
    url = os.environ.get("PRORA_DATABASE_URL", "")
    if not url:
        print("ERROR: export PRORA_DATABASE_URL='postgresql://...'")
        sys.exit(1)
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


async def publish_disease(db_url: str, disease: str) -> bool:
    import pandas as pd
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.jobs.dataset import build_training_dataset
    from app.ml.config import MLConfig
    from app.ml.explainability import local_driver_analysis_many
    from app.ml.features import build_weekly_features
    from app.ml.readiness import assess_training_frame
    from app.ml.registry import ModelRegistry
    from app.ml.service import ForecastService
    from app.models.epidemiology import (
        AlertEvent,
        Forecast,
        ModelVersion,
    )

    registry = ModelRegistry(REGISTRY_PATH)
    horizon = 4
    latest = registry.latest_version(disease, horizon)
    if not latest:
        log.warning(f"  {disease}: sin modelo local, saltando")
        return False

    manifest = registry.manifest(disease, horizon, latest)
    bundle = registry.load(disease, horizon, latest)
    log.info(f"  Modelo local: {latest}, MAE={manifest.get('metrics', {}).get('mae', '?')}")

    ssl_args = {"ssl": True} if "render.com" in db_url or "neon" in db_url else {}
    engine = create_async_engine(db_url, connect_args=ssl_args, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        existing = (
            await session.scalars(
                select(ModelVersion).where(
                    ModelVersion.disease == disease,
                    ModelVersion.horizon_weeks == horizon,
                    ModelVersion.version == latest,
                )
            )
        ).first()
        if existing:
            log.info(f"  ModelVersion {latest} ya existe en BD (id={existing.id}), reutilizando")
            version = existing
        else:
            prev_champions = list(
                (
                    await session.scalars(
                        select(ModelVersion).where(
                            ModelVersion.disease == disease,
                            ModelVersion.horizon_weeks == horizon,
                            ModelVersion.stage == "champion",
                        )
                    )
                ).all()
            )
            for prev in prev_champions:
                prev.stage = "archived"

            version = ModelVersion(
                disease=disease,
                horizon_weeks=horizon,
                version=latest,
                stage="champion",
                artifact_uri=f"local://{REGISTRY_PATH}/{disease}/h{horizon}/{latest}",
                training_started_on=_as_date(manifest.get("training_start")),
                training_ended_on=_as_date(manifest.get("training_end")),
                metrics=_json_safe(manifest.get("metrics", {})),
                feature_names=list(manifest.get("features", [])),
                data_fingerprint=manifest.get("data_fingerprint"),
                activated_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            log.info(f"  ModelVersion insertada: id={version.id}")

        stale_forecast_ids = list(
            await session.scalars(
                select(Forecast.id).where(Forecast.model_version_id == version.id)
            )
        )
        if stale_forecast_ids:
            await session.execute(
                delete(AlertEvent).where(AlertEvent.forecast_id.in_(stale_forecast_ids))
            )
            removed = await session.execute(
                delete(Forecast).where(Forecast.model_version_id == version.id)
            )
            await session.flush()
            log.info(f"  Eliminados {removed.rowcount or len(stale_forecast_ids)} forecasts previos")

        log.info("  Descargando panel para generar forecasts...")
        dataset = await build_training_dataset(session, disease)
        panel = dataset.frame
        log.info(f"  Panel: {len(panel)} filas")

        if len(panel) < 10:
            log.warning(f"  Panel insuficiente para {disease}")
            await session.commit()
            await engine.dispose()
            return False

        config = MLConfig()
        service = ForecastService(registry, config)

        log.info("  Generando proyección de escenario (histórico → 2026)...")
        results = service.forecast_scenario_rollout(
            panel, disease, horizon=horizon, versions={horizon: latest}
        )
        log.info(f"  {len(results)} puntos de escenario generados")

        feature_frame = build_weekly_features(panel, config)
        latest_rows = feature_frame.groupby(
            [config.disease_column, config.territory_column],
            observed=True, sort=False,
        ).tail(1)
        disease_reference = feature_frame[
            feature_frame[config.disease_column].astype(str) == disease
        ]
        baseline = disease_reference[bundle.feature_names].median(numeric_only=True)

        log.info("  Calculando explicaciones (perturbation-based)...")
        t0 = time.time()
        disease_latest = latest_rows[
            latest_rows[config.disease_column].astype(str) == disease
        ].copy()
        try:
            driver_map_raw = local_driver_analysis_many(
                bundle,
                disease_latest,
                baseline=baseline,
                key_column=config.territory_column,
                limit=5,
                chunk_size=96,
            )
            explanation_map: dict[str, tuple[list[dict], str | None]] = {
                k: (v, None) for k, v in driver_map_raw.items()
            }
        except Exception as e:
            log.warning(f"  Explicaciones fallaron: {e}")
            explanation_map = {}

        elapsed = time.time() - t0
        log.info(f"  Explicaciones: {len(explanation_map)} territorios en {elapsed:.1f}s")

        readiness = assess_training_frame(panel, disease, config)
        passes_gate = manifest.get("metrics", {}).get("benchmark", {}).get("passes_baseline_gate", False)

        original_cutoffs: dict[str, str] = {}
        for territory_id in panel[config.territory_column].astype(str).unique():
            subset = panel[panel[config.territory_column].astype(str) == territory_id]
            original_cutoffs[territory_id] = pd.to_datetime(
                subset[config.date_column].max()
            ).date().isoformat()

        eligible_count = 0
        alert_count = 0
        generated_at = datetime.now(UTC)

        for result in results:
            is_first_step = result.issued_week == original_cutoffs.get(result.territory_id)
            if is_first_step:
                drivers, warning = explanation_map.get(
                    result.territory_id, ([], "explanation_unavailable")
                )
            else:
                drivers, warning = [], None
            warnings = list(result.warnings)
            if not readiness.get("operational_forecast_eligible", False):
                result.operationally_eligible = False
                if is_first_step:
                    warnings.append("training_outcome_not_eligible_for_current_operations")
            if not passes_gate:
                result.operationally_eligible = False
                if is_first_step:
                    warnings.append("model_did_not_pass_naive_baseline_gate")
            if warning and is_first_step:
                warnings.append(warning)

            forecast = Forecast(
                municipality_code=result.territory_id,
                disease=result.disease,
                issued_at=generated_at,
                target_week=_as_date(result.target_week),
                horizon_weeks=result.horizon_weeks,
                predicted_cases=float(result.predicted_cases),
                interval_lower=float(result.interval_lower),
                interval_upper=float(result.interval_upper),
                outbreak_probability=float(result.outbreak_probability),
                risk_level=result.risk_level,
                data_completeness=float(result.data_completeness),
                model_version_id=version.id,
                component_predictions=_json_safe(result.model_components),
                drivers=_json_safe(drivers),
                warnings=warnings,
            )
            if hasattr(Forecast, "observation_cutoff"):
                forecast.observation_cutoff = _as_date(result.issued_week)
                forecast.observation_age_days = result.observation_age_days
                forecast.operationally_eligible = result.operationally_eligible

            session.add(forecast)
            if result.operationally_eligible:
                eligible_count += 1

            if passes_gate and float(result.outbreak_probability) >= 0.8:
                await session.flush()
                session.add(AlertEvent(
                    forecast_id=forecast.id,
                    threshold=0.8,
                    status="open" if result.operationally_eligible else "archived",
                ))
                alert_count += 1

        await session.commit()
        log.info(
            f"  Publicado: {len(results)} forecasts, "
            f"{eligible_count} elegibles, {alert_count} alertas"
        )

    await engine.dispose()
    return True


async def main():
    parser = argparse.ArgumentParser(description="Publicar modelos locales en BD de Render")
    parser.add_argument("--disease", type=str, help="Solo una enfermedad")
    args = parser.parse_args()

    db_url = _get_database_url()
    diseases = (args.disease,) if args.disease else DISEASES

    log.info("=== PUBLICACIÓN DE MODELOS ===")
    for disease in diseases:
        log.info(f"\n--- {disease.upper()} ---")
        try:
            ok = await publish_disease(db_url, disease)
            log.info(f"  {disease}: {'OK' if ok else 'SKIP'}")
        except Exception as e:
            log.error(f"  {disease}: FALLO → {e}", exc_info=True)

    log.info("\n=== PUBLICACIÓN COMPLETA ===")


if __name__ == "__main__":
    asyncio.run(main())
