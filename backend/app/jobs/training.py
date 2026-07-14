"""Database-backed, reproducible training and forecast publication workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.dataset import build_training_dataset, persist_training_dataset
from app.ml.concurrency import acquire_model_promotion_locks
from app.ml.config import MLConfig
from app.ml.explainability import local_driver_analysis, local_driver_analysis_many
from app.ml.features import build_supervised_frame, build_weekly_features
from app.ml.models import ModelBundle
from app.ml.readiness import assess_training_frame
from app.ml.registry import ModelRegistry
from app.ml.service import ForecastService
from app.models.epidemiology import (
    AlertEvent,
    Forecast,
    ModelTrainingRun,
    ModelVersion,
    PipelineStatus,
)

EXPLANATION_TERRITORY_CHUNK_SIZE = 64


async def claim_training_job(session: AsyncSession) -> ModelTrainingRun | None:
    statement = (
        select(ModelTrainingRun)
        .where(ModelTrainingRun.status == PipelineStatus.PENDING.value)
        .order_by(ModelTrainingRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await session.scalar(statement)
    if job is None:
        return None
    job.status = PipelineStatus.RUNNING.value
    job.started_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(job)
    return job


async def process_training_job(
    session: AsyncSession,
    job: ModelTrainingRun,
    registry_path: str,
) -> None:
    """Train candidates, persist predictions and atomically promote champions.

    Model artifacts are registered as inactive candidates first. Forecasts refer
    to their exact versions, never to a mutable ``latest`` pointer. Only after
    predictions and explanations are persisted are filesystem pointers and DB
    champion stages moved together, with compensation on failure.
    """

    # Snapshot identifiers before entering a transaction that may roll back.
    # SQLAlchemy expires ORM attributes on rollback; accessing ``job.id`` or
    # ``job.disease`` afterwards from async code can otherwise trigger an
    # implicit refresh and ``MissingGreenlet``.
    job_id = str(job.id)
    disease = str(job.disease)
    horizons = list(job.horizons)
    parameters = dict(job.parameters or {})
    registry = ModelRegistry(registry_path)
    pointer_before: dict[int, str | None] = {}
    activated_versions: dict[int, str] = {}
    try:
        dataset = await build_training_dataset(session, disease)
        panel = dataset.frame
        if panel.empty:
            raise ValueError(
                "No hay observaciones agregadas para entrenar esta enfermedad. "
                "Sincronice/cargue SIVIGILA primero."
            )
        snapshot = persist_training_dataset(dataset, registry.root)
        config = MLConfig()
        readiness = assess_training_frame(panel, disease, config)
        if not readiness["research_training_eligible"]:
            failed = ", ".join(
                key
                for key, requirement in readiness["requirements"].items()
                if not requirement["passes"]
            )
            raise ValueError(
                "Los datos no cumplen el minimo para entrenamiento de investigacion: "
                + (failed or "cobertura epidemiologica insuficiente")
            )
        pipeline_fingerprint = _pipeline_fingerprint(config)
        training_contract_fingerprint = _training_contract_fingerprint(config)
        existing_champions = await _champions(session, disease, horizons)
        if not bool(parameters.get("force")) and _can_reuse(
            existing_champions,
            horizons,
            dataset.fingerprint,
            pipeline_fingerprint,
        ):
            job.status = PipelineStatus.SUCCEEDED.value
            job.result = {
                "reused": True,
                "reason": "same_dataset_and_pipeline",
                "data_fingerprint": dataset.fingerprint,
                "pipeline_fingerprint": pipeline_fingerprint,
                "model_readiness": readiness,
                "models": [
                    {
                        "horizon": horizon,
                        "version": existing_champions[horizon].version,
                        "status": "reused",
                    }
                    for horizon in sorted(existing_champions)
                ],
            }
            job.finished_at = datetime.now(UTC)
            await session.commit()
            return

        service = ForecastService(registry, config)
        lineage = {
            "data_fingerprint": dataset.fingerprint,
            "dataset_manifest": dataset.manifest,
            "dataset_snapshot_sha256": snapshot.sha256,
            "dataset_snapshot_uri": snapshot.uri,
            "training_job_id": job_id,
            "pipeline_fingerprint": pipeline_fingerprint,
            "training_contract_fingerprint": training_contract_fingerprint,
            "model_readiness": readiness,
        }
        receipts = _resumable_receipts(
            service=service,
            panel=panel,
            disease=disease,
            horizons=horizons,
            job_id=job_id,
            data_fingerprint=dataset.fingerprint,
            snapshot_hash=snapshot.sha256,
            pipeline_fingerprint=pipeline_fingerprint,
            training_contract_fingerprint=training_contract_fingerprint,
            config=config,
        )
        resumed_horizons = {int(item["horizon"]) for item in receipts}
        missing_horizons = [horizon for horizon in horizons if horizon not in resumed_horizons]
        if missing_horizons:
            receipts.extend(
                service.train_all(
                    panel,
                    diseases=[disease],
                    horizons=missing_horizons,
                    metadata=lineage,
                    activate_registry=False,
                )
            )
        ready = [item for item in receipts if item.get("status") in {"registered", "resumed"}]
        ready.sort(key=lambda item: int(item["horizon"]))
        if set(int(item["horizon"]) for item in ready) != set(horizons):
            raise ValueError("El conjunto no produjo ningun modelo entrenable")

        versions: dict[int, ModelVersion] = {}
        version_names: dict[int, str] = {}
        for receipt in ready:
            horizon = int(receipt["horizon"])
            version_name = str(receipt["version"])
            manifest = registry.manifest(disease, horizon, version_name)
            trace = {
                "artifact_sha256": manifest["artifact_sha256"],
                "dataset_snapshot_sha256": snapshot.sha256,
                "pipeline_fingerprint": manifest.get("pipeline_fingerprint"),
                "publication_pipeline_fingerprint": pipeline_fingerprint,
                "training_contract_fingerprint": manifest.get("training_contract_fingerprint"),
                "training_job_id": job_id,
                "resume_validation": receipt.get("resume_validation"),
                "runtime": manifest.get("runtime", {}),
                "fold_metrics": manifest.get("fold_metrics", []),
                "config": manifest.get("config", {}),
            }
            version = ModelVersion(
                disease=disease,
                horizon_weeks=horizon,
                version=version_name,
                stage="candidate",
                artifact_uri=str(Path(registry.root) / disease / f"h{horizon}" / version_name),
                training_started_on=_as_date(manifest.get("training_start")),
                training_ended_on=_as_date(manifest.get("training_end")),
                metrics={**_json_safe(manifest.get("metrics", {})), "_trace": trace},
                feature_names=list(manifest.get("features", [])),
                data_fingerprint=dataset.fingerprint,
            )
            session.add(version)
            await session.flush()
            versions[horizon] = version
            version_names[horizon] = version_name

        results = service.forecast_many(
            panel,
            disease,
            horizons=sorted(versions),
            versions=version_names,
        )
        feature_frame = build_weekly_features(panel, config)
        latest_rows = feature_frame.groupby(
            [config.disease_column, config.territory_column],
            observed=True,
            sort=False,
        ).tail(1)
        disease_reference = feature_frame[
            feature_frame[config.disease_column].astype(str) == disease
        ]
        explanation_maps: dict[int, dict[str, tuple[list[dict[str, Any]], str | None]]] = {}
        for horizon, version_name in version_names.items():
            bundle, _ = service.get_artifact(disease, horizon, version_name)
            baseline = disease_reference[bundle.feature_names].median(numeric_only=True)
            explanation_maps[horizon] = _drivers_for_horizon(
                bundle,
                latest_rows,
                baseline,
                chunk_size=EXPLANATION_TERRITORY_CHUNK_SIZE,
            )
        eligible_count = 0
        withheld_count = 0
        explanation_failures = 0
        generated_at = datetime.now(UTC)
        for result in results:
            version = versions[result.horizon_weeks]
            drivers, explanation_warning = explanation_maps[result.horizon_weeks].get(
                result.territory_id,
                ([], "explanation_unavailable"),
            )
            warnings = list(result.warnings)
            if not readiness["operational_forecast_eligible"]:
                result.operationally_eligible = False
                warnings.append("training_outcome_not_eligible_for_current_operations")
                warnings.extend(
                    str(item["code"])
                    for item in readiness["limitations"]
                    if str(item["code"]) not in warnings
                )
            benchmark = version.metrics.get("benchmark", {})
            if benchmark.get("passes_baseline_gate") is not True:
                result.operationally_eligible = False
                warnings.append("model_did_not_pass_naive_baseline_gate")
            if explanation_warning:
                warnings.append(explanation_warning)
                explanation_failures += 1
            forecast_values: dict[str, Any] = {
                "municipality_code": result.territory_id,
                "disease": result.disease,
                "issued_at": generated_at,
                "target_week": _as_date(result.target_week),
                "horizon_weeks": result.horizon_weeks,
                "predicted_cases": result.predicted_cases,
                "interval_lower": result.interval_lower,
                "interval_upper": result.interval_upper,
                "outbreak_probability": result.outbreak_probability,
                "risk_level": result.risk_level,
                "data_completeness": result.data_completeness,
                "model_version_id": version.id,
                "component_predictions": result.model_components,
                "drivers": drivers,
                "warnings": warnings,
            }
            # These columns are part of the production schema. Keeping the
            # assignment conditional also supports an older DB during migration.
            if hasattr(Forecast, "observation_cutoff"):
                forecast_values.update(
                    {
                        "observation_cutoff": _as_date(result.issued_week),
                        "observation_age_days": result.observation_age_days,
                        "operationally_eligible": result.operationally_eligible,
                    }
                )
            forecast = Forecast(**forecast_values)
            session.add(forecast)
            await session.flush()
            if result.operationally_eligible:
                eligible_count += 1
            else:
                withheld_count += 1
            # Preserve high-risk retrospective signals when the model passed
            # the baseline gate but the observation cut-off is no longer
            # current. They are never exposed as active alerts: the archived
            # status and the forecast operational flag keep the distinction
            # explicit for audit/history views.
            if (
                benchmark.get("passes_baseline_gate") is True
                and result.outbreak_probability >= 0.8
            ):
                session.add(
                    AlertEvent(
                        forecast_id=forecast.id,
                        threshold=0.8,
                        status="open" if result.operationally_eligible else "archived",
                    )
                )

        await acquire_model_promotion_locks(session, disease, versions)
        for horizon, version in versions.items():
            pointer_before[horizon] = registry.latest_version(disease, horizon)
            previous = list(
                (
                    await session.scalars(
                        select(ModelVersion)
                        .where(
                            ModelVersion.disease == disease,
                            ModelVersion.horizon_weeks == horizon,
                            ModelVersion.stage == "champion",
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for item in previous:
                item.stage = "archived"
            version.stage = "champion"
            version.activated_at = datetime.now(UTC)
            registry.activate(disease, horizon, version.version)
            activated_versions[horizon] = version.version

        job.status = PipelineStatus.SUCCEEDED.value
        job.result = {
            "models": receipts,
            "forecasts_created": len(results),
            "forecasts_operationally_eligible": eligible_count,
            "forecasts_withheld_as_stale": withheld_count,
            "explanation_failures": explanation_failures,
            "data_fingerprint": dataset.fingerprint,
            "dataset_snapshot_sha256": snapshot.sha256,
            "pipeline_fingerprint": pipeline_fingerprint,
            "training_contract_fingerprint": training_contract_fingerprint,
            "dataset": dataset.manifest,
            "model_readiness": readiness,
        }
        job.finished_at = datetime.now(UTC)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if activated_versions:
            try:
                await acquire_model_promotion_locks(session, disease, activated_versions)
                _restore_registry_pointers(
                    registry,
                    disease,
                    pointer_before,
                    activated_versions,
                )
                await session.commit()
            except Exception:
                await session.rollback()
        persisted = await session.get(ModelTrainingRun, job_id)
        if persisted is not None:
            persisted.status = PipelineStatus.FAILED.value
            persisted.error_message = str(exc)[:4000]
            persisted.finished_at = datetime.now(UTC)
            await session.commit()


async def _champions(
    session: AsyncSession,
    disease: str,
    horizons: list[int],
) -> dict[int, ModelVersion]:
    models = list(
        (
            await session.scalars(
                select(ModelVersion).where(
                    ModelVersion.disease == disease,
                    ModelVersion.horizon_weeks.in_(horizons),
                    ModelVersion.stage == "champion",
                )
            )
        ).all()
    )
    return {model.horizon_weeks: model for model in models}


def _can_reuse(
    champions: dict[int, ModelVersion],
    horizons: list[int],
    data_fingerprint: str,
    pipeline_fingerprint: str,
) -> bool:
    if set(champions) != set(horizons):
        return False
    return all(
        model.data_fingerprint == data_fingerprint
        and model.metrics.get("_trace", {}).get("pipeline_fingerprint") == pipeline_fingerprint
        for model in champions.values()
    )


def _drivers_for_forecast(
    bundle: ModelBundle,
    latest_rows: pd.DataFrame,
    baseline: pd.Series,
    territory: str,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        row = latest_rows[latest_rows["territory_id"].astype(str) == territory].tail(1).copy()
        if row.empty:
            raise ValueError(f"No feature row for territory {territory}")
        for feature in bundle.feature_names:
            if feature not in row.columns:
                row[feature] = pd.NA
        drivers = _json_safe(local_driver_analysis(bundle, row, baseline=baseline, limit=6))
        return drivers, None
    except (KeyError, ValueError, TypeError, OSError, FileNotFoundError):
        return [], "explanation_unavailable"


def _drivers_for_horizon(
    bundle: ModelBundle,
    latest_rows: pd.DataFrame,
    baseline: pd.Series,
    *,
    chunk_size: int,
) -> dict[str, tuple[list[dict[str, Any]], str | None]]:
    """Batch explanations while isolating failures to their exact territory."""

    scoped = latest_rows[latest_rows["disease"].astype(str) == bundle.disease].copy()
    scoped["territory_id"] = scoped["territory_id"].astype(str)
    for feature in bundle.feature_names:
        if feature not in scoped.columns:
            scoped[feature] = pd.NA
    output: dict[str, tuple[list[dict[str, Any]], str | None]] = {}
    for start in range(0, len(scoped), chunk_size):
        chunk = scoped.iloc[start : start + chunk_size]
        try:
            batch = local_driver_analysis_many(
                bundle,
                chunk,
                baseline=baseline,
                key_column="territory_id",
                limit=6,
                chunk_size=max(1, len(chunk)),
            )
            output.update(
                {territory: (_json_safe(drivers), None) for territory, drivers in batch.items()}
            )
        except (KeyError, ValueError, TypeError, OSError, FileNotFoundError):
            # Preserve the previous per-territory failure semantics: a malformed
            # row cannot suppress explanations for the rest of its chunk.
            for territory in chunk["territory_id"].astype(str):
                output[territory] = _drivers_for_forecast(
                    bundle,
                    chunk,
                    baseline,
                    territory,
                )
    return output


def _pipeline_fingerprint(config: MLConfig) -> str:
    digest = hashlib.sha256(
        json.dumps(config.as_dict(), sort_keys=True, default=list).encode("utf-8")
    )
    ml_root = Path(__file__).parents[1] / "ml"
    pipeline_files = [*ml_root.glob("*.py"), Path(__file__), Path(__file__).with_name("dataset.py")]
    for path in sorted(pipeline_files, key=lambda item: str(item)):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _training_contract_fingerprint(config: MLConfig) -> str:
    """Hash only code that can change fitted model inputs or predictions."""

    digest = hashlib.sha256(
        json.dumps(config.as_dict(), sort_keys=True, default=list).encode("utf-8")
    )
    ml_root = Path(__file__).parents[1] / "ml"
    contract_files = [
        ml_root / name
        for name in ("config.py", "features.py", "metrics.py", "models.py", "validation.py")
    ]
    contract_files.append(Path(__file__).with_name("dataset.py"))
    for path in contract_files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _resumable_receipts(
    *,
    service: ForecastService,
    panel: pd.DataFrame,
    disease: str,
    horizons: list[int],
    job_id: str,
    data_fingerprint: str,
    snapshot_hash: str,
    pipeline_fingerprint: str,
    training_contract_fingerprint: str,
    config: MLConfig,
) -> list[dict[str, Any]]:
    """Recover verified artifacts created by this exact interrupted job only."""

    receipts: list[dict[str, Any]] = []
    expected_config = _json_safe(config.as_dict())
    for horizon in sorted(set(horizons)):
        for candidate in service.registry.list_versions(disease, horizon):
            if (
                candidate.get("training_job_id") != job_id
                or candidate.get("data_fingerprint") != data_fingerprint
                or candidate.get("dataset_snapshot_sha256") != snapshot_hash
            ):
                continue
            version = str(candidate.get("version", ""))
            if not version:
                continue
            try:
                bundle, manifest = service.get_artifact(disease, horizon, version)
            except (OSError, FileNotFoundError, TypeError, ValueError):
                continue
            validation: str | None = None
            if manifest.get("pipeline_fingerprint") == pipeline_fingerprint:
                validation = "exact_pipeline"
            elif manifest.get("training_contract_fingerprint") == training_contract_fingerprint:
                validation = "same_training_contract_orchestration_changed"
            elif _json_safe(
                manifest.get("config", {})
            ) == expected_config and _feature_contract_matches(
                panel, disease, horizon, bundle, config
            ):
                # Legacy artifacts predate the split training-contract hash. This
                # fallback is deliberately restricted to the identical job id,
                # dataset and snapshot; it is never used for cross-job reuse.
                validation = "legacy_same_job_config_and_feature_contract"
            if validation is None:
                service.clear_cache()
                continue
            receipts.append(
                {
                    "disease": disease,
                    "horizon": horizon,
                    "version": version,
                    "status": "resumed",
                    "metrics": bundle.metrics,
                    "resume_validation": validation,
                    "orchestration_only_change": (
                        manifest.get("pipeline_fingerprint") != pipeline_fingerprint
                    ),
                }
            )
            break
    return receipts


def _feature_contract_matches(
    panel: pd.DataFrame,
    disease: str,
    horizon: int,
    bundle: ModelBundle,
    config: MLConfig,
) -> bool:
    try:
        frame, features = build_supervised_frame(panel, horizon, config)
        target = f"target_cases_h{horizon}"
        frame = frame[
            (frame[config.disease_column] == disease) & frame[target].notna()
        ].sort_values(config.date_column)
        retained = [feature for feature in features if frame[feature].notna().any()]
        if not len(frame):
            return False
        return (
            retained == bundle.feature_names
            and len(frame) == bundle.training_rows
            and str(frame[config.date_column].min().date()) == bundle.training_start
            and str(frame[config.date_column].max().date()) == bundle.training_end
            and _json_safe(bundle.config) == _json_safe(config.as_dict())
        )
    except (KeyError, TypeError, ValueError):
        return False


def _restore_registry_pointers(
    registry: ModelRegistry,
    disease: str,
    previous: dict[int, str | None],
    activated: dict[int, str],
) -> None:
    for horizon, candidate in activated.items():
        prior = previous.get(horizon)
        try:
            registry.restore_latest(
                disease,
                horizon,
                prior,
                expected_current=candidate,
            )
        except (OSError, FileNotFoundError, ValueError):
            # The DB transaction is still rolled back. An operator can repair a
            # filesystem pointer from the immutable manifest if storage failed.
            continue


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, float) and pd.isna(value):
        return None
    return value
