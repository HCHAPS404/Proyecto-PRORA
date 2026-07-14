from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.jobs.training import _resumable_receipts
from app.ml import ForecastService, MLConfig, ModelRegistry
from app.ml.models import train_model


def _synthetic_history(weeks: int = 92) -> pd.DataFrame:
    rng = np.random.default_rng(44)
    dates = pd.date_range("2024-01-01", periods=weeks, freq="W-MON")
    rows: list[dict[str, object]] = []
    for territory_index, territory in enumerate(("05001", "76001", "11001")):
        previous = 15.0 + 3 * territory_index
        for index, week in enumerate(dates):
            rain = 110 + 45 * np.sin(2 * np.pi * (index - 5) / 52) + rng.normal(0, 5)
            temperature = 23.5 + territory_index * 0.7 + 1.8 * np.sin(2 * np.pi * index / 52)
            signal = 9 * np.sin(2 * np.pi * index / 52) + 0.055 * rain
            cases = max(0, 0.55 * previous + 8 + signal + rng.normal(0, 2.2))
            previous = cases
            rows.append(
                {
                    "week": week,
                    "disease": "dengue",
                    "territory_id": territory,
                    "cases": round(cases),
                    "precipitation": rain,
                    "temperature": temperature,
                    "humidity": 66 + rain * 0.08,
                    "pai_health_system_access_proxy": 84 - index * 0.035,
                    "deforestation": max(0, rng.normal(2 + territory_index, 0.25)),
                    "water_access": 78 + territory_index * 3,
                    "overcrowding": 11 - territory_index,
                    "population": 400_000 + territory_index * 250_000,
                }
            )
    return pd.DataFrame(rows)


def _config() -> MLConfig:
    return MLConfig(
        min_train_weeks=36,
        validation_weeks=4,
        n_splits=2,
        enable_lstm=False,
        rf_estimators=28,
        hgb_iterations=35,
        random_state=7,
    )


def test_training_produces_stack_metrics_and_conformal_interval() -> None:
    bundle = train_model(_synthetic_history(), "dengue", 3, _config())
    assert bundle.training_rows > 100
    assert bundle.model.temporal_backend == "ridge_fallback"
    assert bundle.conformal_radius >= 0
    assert {"mae", "rmse", "auc", "sensitivity", "specificity"}.issubset(bundle.metrics)
    temporal = [
        report
        for report in bundle.fold_metrics
        if report["validation"] == "temporal_expanding_window"
    ]
    territorial = [
        report
        for report in bundle.fold_metrics
        if report["validation"] == "territorial_leave_department_out"
    ]
    assert len(temporal) == 2
    assert len(territorial) == 3
    assert bundle.metrics["probability_calibration"]["method"] in {
        "constant",
        "isotonic",
        "platt",
    }
    assert "territorial_mae" in bundle.metrics
    benchmark = bundle.metrics["benchmark"]
    winner = benchmark["best_candidate"]
    assert winner in {
        "random_forest",
        "hist_gradient_boosting",
        "temporal_lstm",
        "temporal_stacking_ensemble",
    }
    assert benchmark["production_model"] == winner
    assert bundle.metrics["production_model"] == winner
    assert bundle.model.production_model_ == winner
    assert np.isclose(bundle.metrics["mae"], benchmark["candidates"][winner]["mae"])
    assert {"persistence", "seasonal_naive_52w"}.issubset(benchmark["candidates"])
    assert {
        "random_forest",
        "hist_gradient_boosting",
        "temporal_lstm",
        "temporal_stacking_ensemble",
    }.issubset(benchmark["candidates"])
    assert isinstance(benchmark["passes_baseline_gate"], bool)
    assert benchmark["fold_reports"]
    assert bundle.metrics["territorial_benchmark"]["folds"] == 3
    assert bundle.metrics["territorial_benchmark"]["production_model"] == winner
    assert {
        report["production_model"] for report in territorial
    } == {winner}
    assert bundle.config["territorial_meta_splits"] == 1
    assert winner in bundle.metrics["validation_protocol"]["conformal_calibration"]
    assert bundle.metrics["probability_calibration"]["production_model"] == winner
    if winner == "temporal_stacking_ensemble":
        assert "chronological internal meta holdout" in (
            bundle.metrics["validation_protocol"]["territorial"]
        )
    else:
        assert winner in bundle.metrics["validation_protocol"]["territorial"]
    assert set(bundle.model.model_names_) == {
        "random_forest",
        "hist_gradient_boosting",
        "temporal_lstm",
    }

    # Inference is genuinely routed to a selected component, while every
    # component remains embedded for explainability and benchmark inspection.
    probe = pd.DataFrame(
        {name: np.asarray([0.0, 1.0], dtype=float) for name in bundle.feature_names}
    )
    bundle.model.select_production_model("random_forest")
    routed = bundle.model.predict(probe)
    expected = np.maximum(
        0.0, np.asarray(bundle.model.estimators_["random_forest"].predict(probe))
    )
    assert np.allclose(routed, expected)
    bundle.model.select_production_model(winner)


def test_registry_and_forecast_round_trip(tmp_path, monkeypatch) -> None:
    history = _synthetic_history()
    config = _config()
    registry = ModelRegistry(tmp_path / "registry")
    service = ForecastService(registry, config)
    job_id = "resume-this-job-only"
    receipts = service.train_all(
        history,
        diseases=["dengue"],
        horizons=[3, 4],
        metadata={
            "data_snapshot": "synthetic-test",
            "training_job_id": job_id,
            "data_fingerprint": "data-fingerprint",
            "dataset_snapshot_sha256": "snapshot-hash",
            "pipeline_fingerprint": "original-pipeline",
        },
    )
    assert [receipt["status"] for receipt in receipts] == ["registered", "registered"]

    results = service.forecast(history, "dengue", "76001", horizons=[3, 4])
    assert len(results) == 2
    for forecast in results:
        assert forecast.predicted_cases >= 0
        assert forecast.interval_lower <= forecast.predicted_cases <= forecast.interval_upper
        assert 0 <= forecast.outbreak_probability <= 1
        assert forecast.risk_level in {"low", "moderate", "high", "critical"}
        assert set(forecast.model_components) == {
            "random_forest",
            "hist_gradient_boosting",
            "temporal_lstm",
        }
        assert forecast.model_version

    pointer = tmp_path / "registry" / "dengue" / "h3" / "latest.json"
    version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
    manifest = registry.manifest("dengue", 3, version)
    assert manifest["data_snapshot"] == "synthetic-test"
    assert manifest["artifact_sha256"]
    assert manifest["config"]["random_state"] == 7
    assert manifest["fold_metrics"]
    assert registry.verify("dengue", 3, version)["valid"] is True
    assert len(registry.list_versions("dengue", 3)) == 1

    service.clear_cache()
    artifact_loads = 0
    feature_builds = 0
    original_load = registry.load_with_manifest

    def counted_load(disease, horizon, selected_version=None):
        nonlocal artifact_loads
        artifact_loads += 1
        return original_load(disease, horizon, selected_version)

    from app.ml import service as service_module

    original_feature_build = service_module.build_weekly_features

    def counted_feature_build(data, selected_config):
        nonlocal feature_builds
        feature_builds += 1
        return original_feature_build(data, selected_config)

    monkeypatch.setattr(registry, "load_with_manifest", counted_load)
    monkeypatch.setattr(service_module, "build_weekly_features", counted_feature_build)
    batched = service.forecast_many(history, "dengue", horizons=[3, 4])
    assert len(batched) == 6
    assert artifact_loads == 2
    assert feature_builds == 1

    # A later request on the same service reuses both immutable versions.
    service.forecast(history, "dengue", "76001", horizons=[3, 4])
    assert artifact_loads == 2

    resumer = ForecastService(registry, config)
    resumed = _resumable_receipts(
        service=resumer,
        panel=history,
        disease="dengue",
        horizons=[3, 4],
        job_id=job_id,
        data_fingerprint="data-fingerprint",
        snapshot_hash="snapshot-hash",
        pipeline_fingerprint="changed-orchestration-pipeline",
        training_contract_fingerprint="new-contract-not-in-legacy-manifest",
        config=config,
    )
    assert [item["status"] for item in resumed] == ["resumed", "resumed"]
    assert {
        item["resume_validation"] for item in resumed
    } == {"legacy_same_job_config_and_feature_contract"}
    assert all(item["orchestration_only_change"] for item in resumed)

    not_same_job = _resumable_receipts(
        service=ForecastService(registry, config),
        panel=history,
        disease="dengue",
        horizons=[3, 4],
        job_id="different-job",
        data_fingerprint="data-fingerprint",
        snapshot_hash="snapshot-hash",
        pipeline_fingerprint="original-pipeline",
        training_contract_fingerprint="irrelevant",
        config=config,
    )
    assert not_same_job == []
