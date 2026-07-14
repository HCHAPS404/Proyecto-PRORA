"""Predictive estimators and training orchestration for PRORA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import MLConfig
from .features import build_supervised_frame
from .metrics import aggregate_fold_metrics, regression_and_outbreak_metrics
from .validation import expanding_window_splits, territorial_group_splits

try:  # pragma: no cover - exercised only by installations with the ML extra.
    import torch
    from torch import nn
except ImportError:  # pragma: no cover - deterministic fallback is covered.
    torch = None
    nn = None


if nn is not None:  # pragma: no cover - depends on optional PyTorch.

    class _LSTMNetwork(nn.Module):
        def __init__(self, hidden_size: int) -> None:
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden_size, batch_first=True)
            self.output = nn.Linear(hidden_size, 1)

        def forward(self, inputs: Any) -> Any:
            sequence, _ = self.lstm(inputs)
            return self.output(sequence[:, -1, :]).squeeze(-1)


class TorchOrRidgeRegressor(RegressorMixin, BaseEstimator):
    """A real LSTM with a deterministic lightweight fallback.

    Tabular temporal features are interpreted as an ordered feature sequence.
    In environments without PyTorch, Ridge is used and ``backend_`` explicitly
    records the fallback, making model manifests operationally transparent.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        epochs: int = 35,
        hidden_size: int = 24,
        random_state: int = 42,
    ) -> None:
        self.enabled = enabled
        self.epochs = epochs
        self.hidden_size = hidden_size
        self.random_state = random_state

    def fit(self, X: Any, y: Any) -> TorchOrRidgeRegressor:
        matrix = self._select_temporal_matrix(X, fitting=True)
        targets = np.asarray(y, dtype=np.float32)
        self.imputer_ = SimpleImputer(strategy="median", keep_empty_features=True)
        self.scaler_ = StandardScaler()
        matrix = self.imputer_.fit_transform(matrix)
        matrix = self.scaler_.fit_transform(matrix).astype(np.float32)

        if self.enabled and torch is not None:
            torch.manual_seed(self.random_state)
            np.random.seed(self.random_state)
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            self.model_ = _LSTMNetwork(self.hidden_size)
            optimizer = torch.optim.Adam(self.model_.parameters(), lr=0.012)
            loss_function = torch.nn.SmoothL1Loss()
            inputs = torch.from_numpy(matrix[:, :, None])
            expected = torch.from_numpy(targets)
            self.model_.train()
            for _ in range(self.epochs):
                optimizer.zero_grad(set_to_none=True)
                output = self.model_(inputs)
                loss = loss_function(output, expected)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model_.parameters(), max_norm=1.0)
                optimizer.step()
            self.model_.eval()
            self.backend_ = "pytorch_lstm"
        else:
            self.model_ = Ridge(alpha=2.0)
            self.model_.fit(matrix, targets)
            self.backend_ = "ridge_fallback"
        return self

    def predict(self, X: Any) -> np.ndarray:
        matrix = self._select_temporal_matrix(X, fitting=False)
        matrix = self.scaler_.transform(self.imputer_.transform(matrix)).astype(np.float32)
        if self.backend_ == "pytorch_lstm":  # pragma: no cover - optional extra.
            with torch.no_grad():
                result = self.model_(torch.from_numpy(matrix[:, :, None])).cpu().numpy()
            return result.astype(float)
        return np.asarray(self.model_.predict(matrix), dtype=float)

    def _select_temporal_matrix(self, X: Any, *, fitting: bool) -> np.ndarray:
        if fitting:
            columns = list(getattr(X, "columns", []))
            lag_columns = [name for name in columns if name.startswith("cases_lag_")]
            lag_columns.sort(key=lambda name: int(name.rsplit("_", 1)[1]), reverse=True)
            ordered = [*lag_columns]
            if "cases_current" in columns:
                ordered.append("cases_current")
            if len(ordered) >= 3:
                self.temporal_indices_ = [columns.index(name) for name in ordered]
            else:
                self.temporal_indices_ = list(range(len(columns)))
        matrix = np.asarray(X, dtype=np.float32)
        return matrix[:, self.temporal_indices_]


def _base_estimators(config: MLConfig) -> dict[str, BaseEstimator]:
    def imputer() -> SimpleImputer:
        return SimpleImputer(strategy="median", keep_empty_features=True)

    return {
        "random_forest": Pipeline(
            [
                ("imputer", imputer()),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=config.rf_estimators,
                        min_samples_leaf=3,
                        max_features=0.75,
                        n_jobs=-1,
                        random_state=config.random_state,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("imputer", imputer()),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        max_iter=config.hgb_iterations,
                        learning_rate=0.055,
                        max_leaf_nodes=18,
                        l2_regularization=1.0,
                        random_state=config.random_state,
                    ),
                ),
            ]
        ),
        "temporal_lstm": TorchOrRidgeRegressor(
            enabled=config.enable_lstm,
            epochs=config.lstm_epochs,
            hidden_size=config.lstm_hidden_size,
            random_state=config.random_state,
        ),
    }


class TemporalStackingEnsemble:
    """Stack heterogeneous regressors using expanding-window OOF predictions."""

    def __init__(self, config: MLConfig) -> None:
        self.config = config

    def fit(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        dates: pd.Series,
        *,
        n_splits: int | None = None,
    ) -> TemporalStackingEnsemble:
        targets = np.asarray(y, dtype=float)
        templates = _base_estimators(self.config)
        names = list(templates)
        oof_matrix = np.full((len(X), len(names)), np.nan, dtype=float)
        fold_ids = np.full(len(X), -1, dtype=int)

        try:
            splits = list(
                expanding_window_splits(
                    dates,
                    min_train_periods=self.config.min_train_weeks,
                    validation_periods=self.config.validation_weeks,
                    n_splits=n_splits or self.config.n_splits,
                )
            )
        except ValueError as validation_error:
            # Small municipal pilots still receive a chronological holdout.
            date_values = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
            unique_dates = np.asarray(sorted(date_values.unique()))
            split_week = max(4, int(len(unique_dates) * 0.75))
            if split_week >= len(unique_dates):
                raise ValueError(
                    "At least 12 supervised rows are required to train a model"
                ) from validation_error
            training_weeks = unique_dates[:split_week]
            validation_weeks = unique_dates[split_week:]
            train_idx = np.flatnonzero(date_values.isin(training_weeks).to_numpy())
            validation_idx = np.flatnonzero(date_values.isin(validation_weeks).to_numpy())
            splits = [(train_idx, validation_idx)]

        for fold, (train_idx, validation_idx) in enumerate(splits):
            for column, name in enumerate(names):
                estimator = clone(templates[name])
                estimator.fit(X.iloc[train_idx], targets[train_idx])
                oof_matrix[validation_idx, column] = estimator.predict(X.iloc[validation_idx])
            fold_ids[validation_idx] = fold

        complete = np.all(np.isfinite(oof_matrix), axis=1)
        if complete.sum() < 3:
            raise ValueError("Temporal validation produced too few out-of-fold rows")
        meta_template = Pipeline(
            [("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0, positive=True))]
        )
        # Evaluate the stack chronologically: the meta-model for a fold can only
        # see component predictions from earlier folds. The first fold uses the
        # robust simple mean until meta-training evidence exists.
        temporal_stack = np.full(len(X), np.nan, dtype=float)
        for fold in sorted(np.unique(fold_ids[complete])):
            current = complete & (fold_ids == fold)
            previous = complete & (fold_ids < fold)
            if previous.sum() >= 5:
                fold_meta = clone(meta_template)
                fold_meta.fit(oof_matrix[previous], targets[previous])
                temporal_stack[current] = fold_meta.predict(oof_matrix[current])
            else:
                temporal_stack[current] = oof_matrix[current].mean(axis=1)

        self.meta_model_ = clone(meta_template)
        self.meta_model_.fit(oof_matrix[complete], targets[complete])
        self.validation_predictions_ = np.maximum(0.0, temporal_stack[complete])
        self.stacking_predictions_ = np.maximum(0.0, self.meta_model_.predict(oof_matrix[complete]))
        self.oof_targets_ = targets[complete]
        self.oof_indices_ = np.flatnonzero(complete)
        self.oof_fold_ids_ = fold_ids[complete]
        self.oof_components_ = oof_matrix[complete]

        self.estimators_ = {}
        for name, template in templates.items():
            fitted = clone(template)
            fitted.fit(X, targets)
            self.estimators_[name] = fitted
        self.model_names_ = names
        # The temporal stack remains the backwards-compatible default until
        # the benchmark explicitly selects the lowest-MAE candidate.
        self.select_production_model("temporal_stacking_ensemble")
        return self

    def select_production_model(self, name: str) -> TemporalStackingEnsemble:
        """Route inference and calibration to one benchmarked candidate.

        Every component is still retained in the artifact for audit and model
        comparison.  Only the candidate chosen on temporal OOF MAE is used for
        the bundle's production prediction.
        """

        eligible = {"temporal_stacking_ensemble", *self.model_names_}
        if name not in eligible:
            raise ValueError(
                f"Unknown production candidate '{name}'. Expected one of: "
                + ", ".join(sorted(eligible))
            )
        self.production_model_ = name
        if name == "temporal_stacking_ensemble":
            selected = self.validation_predictions_
        else:
            position = self.model_names_.index(name)
            selected = self.oof_components_[:, position]
        self.production_oof_predictions_ = np.maximum(
            0.0, np.asarray(selected, dtype=float)
        )
        return self

    def predict_components(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        return {
            name: np.maximum(0.0, np.asarray(estimator.predict(X), dtype=float))
            for name, estimator in self.estimators_.items()
        }

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        production_model = getattr(
            self, "production_model_", "temporal_stacking_ensemble"
        )
        components = self.predict_components(X)
        if production_model != "temporal_stacking_ensemble":
            if production_model not in components:
                raise ValueError(
                    f"Artifact production candidate '{production_model}' is unavailable"
                )
            return components[production_model]
        matrix = np.column_stack([components[name] for name in self.model_names_])
        return np.maximum(0.0, np.asarray(self.meta_model_.predict(matrix), dtype=float))

    @property
    def temporal_backend(self) -> str:
        temporal = self.estimators_["temporal_lstm"]
        return getattr(temporal, "backend_", "unknown")


@dataclass
class ModelBundle:
    """Serializable model plus the contract required for safe inference."""

    disease: str
    horizon: int
    feature_names: list[str]
    model: TemporalStackingEnsemble
    outbreak_threshold: float
    conformal_radius: float
    metrics: dict[str, Any]
    fold_metrics: list[dict[str, Any]]
    config: dict[str, Any]
    probability_calibrator: Any
    calibration_method: str
    territory_thresholds: dict[str, float]
    trained_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    training_rows: int = 0
    training_start: str = ""
    training_end: str = ""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return self.model.predict(features[self.feature_names])

    def interval(self, prediction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        values = np.asarray(prediction, dtype=float)
        return np.maximum(0.0, values - self.conformal_radius), values + self.conformal_radius

    def outbreak_probability(
        self,
        prediction: np.ndarray,
        territory: str,
        threshold: float | None = None,
    ) -> np.ndarray:
        values = np.asarray(prediction, dtype=float)
        local_threshold = (
            float(threshold)
            if threshold is not None and np.isfinite(threshold)
            else self.territory_thresholds.get(str(territory), self.outbreak_threshold)
        )
        margins = values - local_threshold
        if self.calibration_method == "constant":
            return np.full(len(values), float(self.probability_calibrator), dtype=float)
        if self.calibration_method == "isotonic":
            return np.asarray(self.probability_calibrator.predict(margins), dtype=float)
        return np.asarray(
            self.probability_calibrator.predict_proba(margins.reshape(-1, 1))[:, 1],
            dtype=float,
        )


def _conformal_radius(residuals: np.ndarray, alpha: float) -> float:
    finite = np.abs(np.asarray(residuals, dtype=float))
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 0.0
    level = min(1.0, np.ceil((len(finite) + 1) * (1 - alpha)) / len(finite))
    return float(np.quantile(finite, level, method="higher"))


def train_model(
    data: pd.DataFrame,
    disease: str,
    horizon: int,
    config: MLConfig | None = None,
) -> ModelBundle:
    """Train one disease/horizon model with temporal validation and calibration."""

    cfg = config or MLConfig()
    cfg.validate()
    disease_key = cfg.assert_disease(disease)
    frame, features = build_supervised_frame(data, horizon, cfg)
    frame = frame[frame[cfg.disease_column] == disease_key].copy()
    target_name = f"target_cases_h{horizon}"
    seasonal_name = f"seasonal_naive_h{horizon}"
    seasonal_lag = max(1, 52 - horizon)
    frame[seasonal_name] = frame.groupby(
        [cfg.disease_column, cfg.territory_column],
        sort=False,
        observed=True,
    )[cfg.target_column].shift(seasonal_lag)
    frame = frame[frame[target_name].notna()].sort_values(cfg.date_column).reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"No supervised rows available for {disease_key} at h={horizon}")

    # Columns that are entirely absent in training cannot be imputed and add no
    # signal. The exact retained contract is persisted in the bundle.
    features = [name for name in features if frame[name].notna().any()]
    X = frame[features]
    y = frame[target_name].to_numpy(dtype=float)
    dates = frame[cfg.date_column]
    threshold_values = frame["outbreak_threshold"].dropna().to_numpy(dtype=float)
    threshold = (
        float(np.median(threshold_values))
        if len(threshold_values)
        else float(np.quantile(y, cfg.outbreak_quantile))
    )
    territory_thresholds = _territory_thresholds(frame, cfg)
    row_thresholds = (
        frame["outbreak_threshold"]
        .fillna(frame[cfg.territory_column].map(territory_thresholds))
        .fillna(threshold)
        .to_numpy(dtype=float)
    )

    ensemble = TemporalStackingEnsemble(cfg).fit(X, y, dates)
    oof_thresholds = row_thresholds[ensemble.oof_indices_]
    benchmark = _temporal_benchmark(
        ensemble,
        frame,
        target_name=target_name,
        seasonal_name=seasonal_name,
        thresholds=row_thresholds,
    )
    production_model = str(
        benchmark.get("best_candidate") or "temporal_stacking_ensemble"
    )
    ensemble.select_production_model(production_model)
    production_oof = ensemble.production_oof_predictions_

    fold_reports: list[dict[str, Any]] = []
    for fold in np.unique(ensemble.oof_fold_ids_):
        mask = ensemble.oof_fold_ids_ == fold
        report = regression_and_outbreak_metrics(
            ensemble.oof_targets_[mask],
            production_oof[mask],
            oof_thresholds[mask],
        )
        report["fold"] = float(fold + 1)
        report["validation"] = "temporal_expanding_window"
        report["production_model"] = production_model
        fold_reports.append(report)
    metrics = aggregate_fold_metrics(fold_reports)
    metrics["production_model"] = production_model
    metrics["benchmark"] = benchmark
    territorial_reports = _territorial_validation_reports(
        X,
        y,
        frame[cfg.territory_column],
        dates,
        row_thresholds,
        frame[seasonal_name].to_numpy(dtype=float),
        cfg,
        production_model,
    )
    territorial_summary = aggregate_fold_metrics(territorial_reports)
    for name, value in territorial_summary.items():
        metrics[f"territorial_{name}"] = value
    metrics["territorial_benchmark"] = _territorial_benchmark_summary(
        territorial_reports, production_model
    )
    fold_reports.extend(territorial_reports)
    residuals = ensemble.oof_targets_ - production_oof
    radius = _conformal_radius(residuals, cfg.conformal_alpha)
    metrics["conformal_coverage_target"] = 1.0 - cfg.conformal_alpha
    metrics["conformal_radius"] = radius
    metrics["conformal_oof_empirical_coverage"] = float(np.mean(np.abs(residuals) <= radius))
    territorial_protocol = (
        "selected temporal stack retrained with held-out DIVIPOLA departments and one "
        "chronological internal meta holdout"
        if production_model == "temporal_stacking_ensemble"
        else (
            f"selected {production_model} candidate refitted without held-out DIVIPOLA "
            "departments"
        )
    )
    metrics["validation_protocol"] = {
        "temporal": "expanding-window by unique epidemiological week",
        "territorial": territorial_protocol,
        "conformal_calibration": (
            f"absolute residuals from {production_model} temporal out-of-fold predictions"
        ),
    }
    outbreak_events = (ensemble.oof_targets_ >= oof_thresholds).astype(int)
    margins = production_oof - oof_thresholds
    calibration_evaluation = _cross_fitted_calibration(
        margins,
        outbreak_events,
        ensemble.oof_fold_ids_,
        cfg.random_state,
    )
    calibrator, calibration_method = _fit_probability_calibrator(
        margins,
        outbreak_events,
        cfg.random_state,
    )
    metrics["probability_calibration"] = {
        "method": calibration_method,
        "brier_score": calibration_evaluation["brier_score"],
        "evaluation": "forward-chaining cross-fitted; first OOF fold excluded",
        "evaluation_rows": calibration_evaluation["evaluation_rows"],
        "evaluation_fold_methods": calibration_evaluation["fold_methods"],
        "calibration_rows": int(len(outbreak_events)),
        "positive_rate": float(outbreak_events.mean()),
        "score": "predicted_cases_minus_origin_specific_threshold",
        "production_model": production_model,
    }

    return ModelBundle(
        disease=disease_key,
        horizon=horizon,
        feature_names=features,
        model=ensemble,
        outbreak_threshold=threshold,
        conformal_radius=radius,
        metrics=metrics,
        fold_metrics=fold_reports,
        config=cfg.as_dict(),
        probability_calibrator=calibrator,
        calibration_method=calibration_method,
        territory_thresholds=territory_thresholds,
        training_rows=len(frame),
        training_start=dates.min().date().isoformat(),
        training_end=dates.max().date().isoformat(),
    )


def _territory_thresholds(frame: pd.DataFrame, config: MLConfig) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for territory, group in frame.groupby(config.territory_column, observed=True):
        values = group["outbreak_threshold"].dropna()
        if len(values):
            thresholds[str(territory)] = float(values.iloc[-1])
    return thresholds


def _fit_probability_calibrator(
    margins: np.ndarray,
    events: np.ndarray,
    random_state: int,
) -> tuple[Any, str]:
    unique, counts = np.unique(events, return_counts=True)
    if len(unique) < 2:
        return float(events.mean()), "constant"
    minority = int(counts.min())
    if len(events) >= 30 and minority >= 5 and len(np.unique(margins)) >= 8:
        calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        calibrator.fit(margins, events)
        return calibrator, "isotonic"
    calibrator = LogisticRegression(random_state=random_state, solver="lbfgs")
    calibrator.fit(margins.reshape(-1, 1), events)
    return calibrator, "platt"


def _calibrated_probabilities(
    calibrator: Any,
    method: str,
    margins: np.ndarray,
) -> np.ndarray:
    if method == "constant":
        return np.full(len(margins), float(calibrator), dtype=float)
    if method == "isotonic":
        return np.asarray(calibrator.predict(margins), dtype=float)
    return np.asarray(calibrator.predict_proba(margins.reshape(-1, 1))[:, 1], dtype=float)


def _cross_fitted_calibration(
    margins: np.ndarray,
    events: np.ndarray,
    fold_ids: np.ndarray,
    random_state: int,
) -> dict[str, Any]:
    predictions = np.full(len(events), np.nan, dtype=float)
    methods: dict[str, str] = {}
    for fold in sorted(np.unique(fold_ids)):
        validation = fold_ids == fold
        training = fold_ids < fold
        if training.sum() < 3:
            continue
        calibrator, method = _fit_probability_calibrator(
            margins[training],
            events[training],
            random_state + int(fold),
        )
        predictions[validation] = _calibrated_probabilities(
            calibrator,
            method,
            margins[validation],
        )
        methods[str(int(fold + 1))] = method
    evaluated = np.isfinite(predictions)
    return {
        "brier_score": (
            float(brier_score_loss(events[evaluated], predictions[evaluated]))
            if evaluated.any()
            else None
        ),
        "evaluation_rows": int(evaluated.sum()),
        "fold_methods": methods,
    }


def _territorial_validation_reports(
    X: pd.DataFrame,
    y: np.ndarray,
    territories: pd.Series,
    dates: pd.Series,
    thresholds: np.ndarray,
    seasonal_reference: np.ndarray,
    config: MLConfig,
    production_model: str,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for fold, (train_idx, validation_idx) in enumerate(
        territorial_group_splits(territories, n_splits=config.territorial_splits),
        start=1,
    ):
        if production_model == "temporal_stacking_ensemble":
            held_out_predictor = TemporalStackingEnsemble(config).fit(
                X.iloc[train_idx].reset_index(drop=True),
                y[train_idx],
                dates.iloc[train_idx].reset_index(drop=True),
                n_splits=config.territorial_meta_splits,
            )
            held_out_predictor.select_production_model(production_model)
            predictions = held_out_predictor.predict(X.iloc[validation_idx])
        else:
            templates = _base_estimators(config)
            if production_model not in templates:
                raise ValueError(f"Unsupported territorial candidate: {production_model}")
            held_out_predictor = clone(templates[production_model])
            held_out_predictor.fit(X.iloc[train_idx], y[train_idx])
            predictions = np.maximum(
                0.0,
                np.asarray(held_out_predictor.predict(X.iloc[validation_idx]), dtype=float),
            )
        report: dict[str, Any] = regression_and_outbreak_metrics(
            y[validation_idx], predictions, thresholds[validation_idx]
        )
        persistence = pd.to_numeric(
            X.iloc[validation_idx].get("cases_current"), errors="coerce"
        ).to_numpy(dtype=float)
        persistence_metrics = _safe_metrics(
            y[validation_idx], persistence, thresholds[validation_idx]
        )
        seasonal_metrics = _safe_metrics(
            y[validation_idx],
            seasonal_reference[validation_idx],
            thresholds[validation_idx],
        )
        report.update(
            {
                "fold": float(fold),
                "validation": "territorial_leave_department_out",
                "production_model": production_model,
                "train_rows": float(len(train_idx)),
                "validation_rows": float(len(validation_idx)),
                "held_out_territories": int(territories.iloc[validation_idx].nunique()),
                "persistence_mae": persistence_metrics.get("mae"),
                "seasonal_naive_mae": seasonal_metrics.get("mae"),
                "mae_skill_vs_persistence": _mae_skill(
                    report.get("mae"), persistence_metrics.get("mae")
                ),
            }
        )
        reports.append(report)
    return reports


def _temporal_benchmark(
    ensemble: TemporalStackingEnsemble,
    frame: pd.DataFrame,
    *,
    target_name: str,
    seasonal_name: str,
    thresholds: np.ndarray,
) -> dict[str, Any]:
    """Compare every learner and two naive baselines on identical OOF folds."""

    indices = ensemble.oof_indices_
    truth = frame[target_name].to_numpy(dtype=float)[indices]
    aligned_thresholds = thresholds[indices]
    predictions: dict[str, np.ndarray] = {
        "temporal_stacking_ensemble": ensemble.validation_predictions_,
        **{
            name: np.maximum(0.0, ensemble.oof_components_[:, position])
            for position, name in enumerate(ensemble.model_names_)
        },
        "persistence": pd.to_numeric(frame["cases_current"], errors="coerce").to_numpy(dtype=float)[
            indices
        ],
        "seasonal_naive_52w": pd.to_numeric(frame[seasonal_name], errors="coerce").to_numpy(
            dtype=float
        )[indices],
    }
    candidate_names = {
        "temporal_stacking_ensemble",
        "random_forest",
        "hist_gradient_boosting",
        "temporal_lstm",
    }
    reports: dict[str, dict[str, Any]] = {}
    fold_reports: list[dict[str, Any]] = []
    for name, values in predictions.items():
        candidate_folds: list[dict[str, Any]] = []
        for fold in sorted(np.unique(ensemble.oof_fold_ids_)):
            mask = ensemble.oof_fold_ids_ == fold
            report = _safe_metrics(truth[mask], values[mask], aligned_thresholds[mask])
            if not report:
                continue
            report.update({"fold": int(fold + 1), "model": name})
            candidate_folds.append(report)
            fold_reports.append(report)
        aggregate = aggregate_fold_metrics(candidate_folds)
        aggregate["evaluated_rows"] = int(
            np.sum(np.isfinite(truth) & np.isfinite(values) & np.isfinite(aligned_thresholds))
        )
        aggregate["kind"] = "candidate" if name in candidate_names else "baseline"
        reports[name] = aggregate

    best_candidate = _best_mae(reports, kind="candidate")
    best_baseline = _best_mae(reports, kind="baseline")
    production_model = best_candidate or "temporal_stacking_ensemble"
    production_mae = reports[production_model].get("mae")
    baseline_mae = reports.get(best_baseline or "", {}).get("mae")
    skill = _mae_skill(production_mae, baseline_mae)
    return {
        "protocol": (
            "same expanding-window out-of-fold weeks and origin-specific outbreak thresholds"
        ),
        "selection_metric": "mae",
        "production_model": production_model,
        "candidates": reports,
        "best_candidate": best_candidate,
        "best_baseline": best_baseline,
        "mae_skill_vs_best_baseline": skill,
        "passes_baseline_gate": bool(skill is not None and skill > 0),
        "fold_reports": fold_reports,
        "seasonal_baseline": (
            "cases observed at forecast target's corresponding week 52 weeks earlier"
        ),
    }


def _safe_metrics(
    truth: np.ndarray,
    prediction: np.ndarray,
    thresholds: np.ndarray,
) -> dict[str, Any]:
    finite = (
        np.isfinite(np.asarray(truth, dtype=float))
        & np.isfinite(np.asarray(prediction, dtype=float))
        & np.isfinite(np.asarray(thresholds, dtype=float))
    )
    if not finite.any():
        return {}
    return regression_and_outbreak_metrics(
        np.asarray(truth, dtype=float)[finite],
        np.asarray(prediction, dtype=float)[finite],
        np.asarray(thresholds, dtype=float)[finite],
    )


def _best_mae(reports: dict[str, dict[str, Any]], *, kind: str) -> str | None:
    eligible = [
        (name, report.get("mae"))
        for name, report in reports.items()
        if report.get("kind") == kind
        and report.get("mae") is not None
        and np.isfinite(float(report["mae"]))
    ]
    return min(eligible, key=lambda item: float(item[1]))[0] if eligible else None


def _mae_skill(model_mae: Any, baseline_mae: Any) -> float | None:
    if model_mae is None or baseline_mae is None:
        return None
    denominator = float(baseline_mae)
    if not np.isfinite(denominator) or denominator <= 0:
        return None
    return float(1.0 - float(model_mae) / denominator)


def _territorial_benchmark_summary(
    reports: list[dict[str, Any]], production_model: str
) -> dict[str, Any]:
    def mean(key: str) -> float | None:
        values = np.asarray([item.get(key, np.nan) for item in reports], dtype=float)
        finite = values[np.isfinite(values)]
        return float(finite.mean()) if len(finite) else None

    return {
        "protocol": (
            f"selected {production_model} candidate retrained with held-out DIVIPOLA "
            "departments"
        ),
        "production_model": production_model,
        "persistence_mae": mean("persistence_mae"),
        "seasonal_naive_mae": mean("seasonal_naive_mae"),
        "mae_skill_vs_persistence": mean("mae_skill_vs_persistence"),
        "folds": len(reports),
    }
