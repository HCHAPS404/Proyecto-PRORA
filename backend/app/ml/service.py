"""Application-facing training and multi-horizon forecast service."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import MLConfig, normalize_disease
from .features import build_weekly_features
from .models import ModelBundle, train_model
from .registry import ModelRegistry


@dataclass(slots=True)
class ForecastResult:
    disease: str
    territory_id: str
    issued_week: str
    target_week: str
    horizon_weeks: int
    predicted_cases: float
    interval_lower: float
    interval_upper: float
    outbreak_probability: float
    risk_level: str
    model_version: str
    model_components: dict[str, float]
    data_completeness: float
    operationally_eligible: bool
    observation_age_days: int
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ForecastService:
    """Train, register and serve 3-4 week municipal predictions."""

    def __init__(
        self,
        registry: ModelRegistry,
        config: MLConfig | None = None,
        *,
        cache_size: int = 8,
    ) -> None:
        self.registry = registry
        self.config = config or MLConfig()
        self.cache_size = max(1, int(cache_size))
        self._artifact_cache: OrderedDict[
            tuple[str, int, str], tuple[ModelBundle, dict[str, Any]]
        ] = OrderedDict()

    def clear_cache(self) -> None:
        self._artifact_cache.clear()

    def get_artifact(
        self,
        disease: str,
        horizon: int,
        version: str | None = None,
    ) -> tuple[ModelBundle, dict[str, Any]]:
        """Return one verified artifact, cached by its immutable version."""

        disease_key = self.config.assert_disease(disease)
        resolved = version or self.registry.latest_version(disease_key, int(horizon))
        if not resolved:
            raise FileNotFoundError(f"No registered model for {disease_key} at h={horizon}")
        key = (disease_key, int(horizon), str(resolved))
        cached = self._artifact_cache.get(key)
        if cached is not None:
            self._artifact_cache.move_to_end(key)
            return cached
        artifact = self.registry.load_with_manifest(disease_key, int(horizon), str(resolved))
        self._remember_artifact(*key, artifact=artifact)
        return artifact

    def _remember_artifact(
        self,
        disease: str,
        horizon: int,
        version: str,
        *,
        artifact: tuple[ModelBundle, dict[str, Any]],
    ) -> None:
        key = (disease, int(horizon), str(version))
        self._artifact_cache[key] = artifact
        self._artifact_cache.move_to_end(key)
        while len(self._artifact_cache) > self.cache_size:
            self._artifact_cache.popitem(last=False)

    def train_all(
        self,
        data: pd.DataFrame,
        *,
        diseases: tuple[str, ...] | list[str] | None = None,
        horizons: tuple[int, ...] | list[int] | None = None,
        metadata: dict[str, Any] | None = None,
        activate_registry: bool = True,
    ) -> list[dict[str, Any]]:
        """Train each requested disease/horizon and return registry receipts."""

        selected_diseases = diseases or list(self.config.diseases)
        selected_horizons = horizons or list(self.config.horizons)
        receipts: list[dict[str, Any]] = []
        for disease in selected_diseases:
            disease_key = self.config.assert_disease(disease)
            available = data[self.config.disease_column].astype(str).map(normalize_disease)
            if not (available == disease_key).any():
                receipts.append(
                    {"disease": disease_key, "status": "skipped", "reason": "no_training_rows"}
                )
                continue
            for horizon in selected_horizons:
                bundle = train_model(data, disease_key, int(horizon), self.config)
                version = self.registry.register(
                    bundle,
                    extra_metadata=metadata,
                    activate=activate_registry,
                )
                manifest = self.registry.manifest(disease_key, int(horizon), version)
                self._remember_artifact(
                    disease_key,
                    int(horizon),
                    version,
                    artifact=(bundle, manifest),
                )
                receipts.append(
                    {
                        "disease": disease_key,
                        "horizon": int(horizon),
                        "version": version,
                        "status": "registered",
                        "metrics": bundle.metrics,
                    }
                )
        return receipts

    def forecast(
        self,
        history: pd.DataFrame,
        disease: str,
        territory_id: str,
        *,
        horizons: tuple[int, ...] | list[int] | None = None,
        versions: dict[int, str] | None = None,
    ) -> list[ForecastResult]:
        return self.forecast_many(
            history,
            disease,
            territories=[str(territory_id)],
            horizons=horizons,
            versions=versions,
        )

    def forecast_many(
        self,
        history: pd.DataFrame,
        disease: str,
        territories: list[str] | None = None,
        *,
        horizons: tuple[int, ...] | list[int] | None = None,
        versions: dict[int, str] | None = None,
    ) -> list[ForecastResult]:
        disease_key = self.config.assert_disease(disease)
        selected_horizons = [int(value) for value in (horizons or self.config.horizons)]
        selected = (
            [str(value) for value in territories]
            if territories
            else sorted(
                history[self.config.territory_column].dropna().astype(str).unique().tolist()
            )
        )
        disease_values = history[self.config.disease_column].astype(str).map(normalize_disease)
        territory_values = history[self.config.territory_column].astype(str)
        scoped = history[(disease_values == disease_key) & territory_values.isin(selected)].copy()
        available = set(scoped[self.config.territory_column].astype(str).unique())
        missing = [territory for territory in selected if territory not in available]
        if missing:
            raise ValueError(f"No history for {disease_key}/{missing[0]}")

        engineered = build_weekly_features(scoped, self.config)
        latest = (
            engineered.groupby(self.config.territory_column, observed=True, sort=False)
            .tail(1)
            .assign(
                **{
                    self.config.territory_column: lambda frame: frame[
                        self.config.territory_column
                    ].astype(str)
                }
            )
            .set_index(self.config.territory_column, drop=False)
            .reindex(selected)
        )
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        by_key: dict[tuple[str, int], ForecastResult] = {}
        for horizon in selected_horizons:
            version = (versions or {}).get(horizon)
            bundle, manifest = self.get_artifact(disease_key, horizon, version)
            for feature in bundle.feature_names:
                if feature not in latest.columns:
                    latest[feature] = np.nan
            feature_frame = latest[bundle.feature_names]
            missing_fractions = feature_frame.isna().mean(axis=1).to_numpy(dtype=float)
            predictions = bundle.predict(feature_frame)
            lower, upper = bundle.interval(predictions)
            components = bundle.model.predict_components(feature_frame)
            issued_values = pd.to_datetime(latest[self.config.date_column])
            thresholds = (
                feature_frame["outbreak_threshold"].to_numpy(dtype=float)
                if "outbreak_threshold" in feature_frame
                else np.full(len(feature_frame), np.nan)
            )
            for index, territory in enumerate(selected):
                issued = pd.Timestamp(issued_values.iloc[index])
                threshold = float(thresholds[index]) if np.isfinite(thresholds[index]) else None
                probability = float(
                    bundle.outbreak_probability(
                        np.asarray([predictions[index]], dtype=float),
                        territory,
                        threshold=threshold,
                    )[0]
                )
                observation_age_days = max(0, int((today - issued.normalize()).days))
                operationally_eligible = (
                    observation_age_days <= self.config.max_forecast_data_age_days
                )
                warnings = []
                if missing_fractions[index] > 0.25:
                    warnings.append("high_feature_missingness")
                if bundle.model.temporal_backend == "ridge_fallback":
                    warnings.append("lstm_extra_unavailable_using_deterministic_fallback")
                if not operationally_eligible:
                    warnings.append("stale_observation_cutoff_not_for_current_operations")
                by_key[(territory, horizon)] = ForecastResult(
                    disease=disease_key,
                    territory_id=territory,
                    issued_week=issued.date().isoformat(),
                    target_week=(issued + pd.Timedelta(weeks=horizon)).date().isoformat(),
                    horizon_weeks=horizon,
                    predicted_cases=round(float(predictions[index]), 3),
                    interval_lower=round(float(lower[index]), 3),
                    interval_upper=round(float(upper[index]), 3),
                    outbreak_probability=round(probability, 4),
                    risk_level=_risk_level(probability),
                    model_version=str(manifest["version"]),
                    model_components={
                        name: round(float(values[index]), 3) for name, values in components.items()
                    },
                    data_completeness=round(1.0 - float(missing_fractions[index]), 4),
                    operationally_eligible=operationally_eligible,
                    observation_age_days=observation_age_days,
                    warnings=warnings,
                )
        return [
            by_key[(territory, horizon)] for territory in selected for horizon in selected_horizons
        ]

    def forecast_scenario_rollout(
        self,
        history: pd.DataFrame,
        disease: str,
        territories: list[str] | None = None,
        *,
        horizon: int | None = None,
        projection_weeks: int | None = None,
        end_year: int | None = None,
        versions: dict[int, str] | None = None,
    ) -> list[ForecastResult]:
        """Iteratively project forward from the last documented week.

        The model is trained on the full historical panel (e.g. 2022–2025).
        Exogenous covariates are held at their last known values while
        seasonality advances with the calendar.  Results are tagged
        ``scenario_projection`` and are not for same-day operations.
        """

        disease_key = self.config.assert_disease(disease)
        step_weeks = int(horizon or max(self.config.horizons))
        max_weeks = int(projection_weeks or self.config.scenario_projection_weeks)
        target_year = int(end_year or self.config.scenario_projection_end_year)
        version = (versions or {}).get(step_weeks)
        bundle, manifest = self.get_artifact(disease_key, step_weeks, version)

        disease_values = history[self.config.disease_column].astype(str).map(normalize_disease)
        territory_values = history[self.config.territory_column].astype(str)
        selected = (
            [str(value) for value in territories]
            if territories
            else sorted(territory_values[disease_values == disease_key].unique().tolist())
        )
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        end_date = pd.Timestamp(year=target_year, month=12, day=31)
        results: list[ForecastResult] = []

        for territory in selected:
            scoped = history[
                (disease_values == disease_key) & (territory_values == territory)
            ].copy()
            if scoped.empty:
                continue
            scoped = scoped.sort_values(self.config.date_column).reset_index(drop=True)
            original_cutoff = pd.to_datetime(scoped[self.config.date_column].iloc[-1]).normalize()
            max_steps = max(1, max_weeks // step_weeks)
            steps_taken = 0

            while steps_taken < max_steps:
                engineered = build_weekly_features(scoped, self.config)
                latest = engineered.iloc[-1]
                issued = pd.to_datetime(latest[self.config.date_column]).normalize()
                target = issued + pd.Timedelta(weeks=step_weeks)
                if target > end_date:
                    break

                for feature in bundle.feature_names:
                    if feature not in latest.index:
                        latest[feature] = np.nan
                feature_row = latest[bundle.feature_names]
                missing_fraction = float(feature_row.isna().mean())
                prediction = float(bundle.predict(feature_row.to_frame().T)[0])
                lower, upper = bundle.interval(np.asarray([prediction], dtype=float))
                components = bundle.model.predict_components(feature_row.to_frame().T)
                threshold = (
                    float(feature_row["outbreak_threshold"])
                    if "outbreak_threshold" in feature_row.index
                    and pd.notna(feature_row["outbreak_threshold"])
                    else None
                )
                probability = float(
                    bundle.outbreak_probability(
                        np.asarray([prediction], dtype=float),
                        territory,
                        threshold=threshold,
                    )[0]
                )
                observation_age_days = max(0, int((today - original_cutoff).days))
                warnings = ["scenario_projection"]
                if missing_fraction > 0.25:
                    warnings.append("high_feature_missingness")
                if bundle.model.temporal_backend == "ridge_fallback":
                    warnings.append("lstm_extra_unavailable_using_deterministic_fallback")
                if observation_age_days > self.config.max_forecast_data_age_days:
                    warnings.append("scenario_from_documented_historical_cutoff")

                results.append(
                    ForecastResult(
                        disease=disease_key,
                        territory_id=territory,
                        issued_week=issued.date().isoformat(),
                        target_week=target.date().isoformat(),
                        horizon_weeks=step_weeks,
                        predicted_cases=round(prediction, 3),
                        interval_lower=round(float(lower[0]), 3),
                        interval_upper=round(float(upper[0]), 3),
                        outbreak_probability=round(probability, 4),
                        risk_level=_risk_level(probability),
                        model_version=str(manifest["version"]),
                        model_components={
                            name: round(float(values[0]), 3)
                            for name, values in components.items()
                        },
                        data_completeness=round(1.0 - missing_fraction, 4),
                        operationally_eligible=False,
                        observation_age_days=observation_age_days,
                        warnings=warnings,
                    )
                )

                synthetic = scoped.iloc[-1].copy()
                synthetic[self.config.date_column] = target
                synthetic[self.config.target_column] = max(0.0, prediction)
                scoped = pd.concat([scoped, pd.DataFrame([synthetic])], ignore_index=True)
                steps_taken += 1

        return results


def _risk_level(probability: float) -> str:
    if probability >= 0.80:
        return "critical"
    if probability >= 0.60:
        return "high"
    if probability >= 0.35:
        return "moderate"
    return "low"
