"""Model-agnostic explainability with an optional SHAP enhancement."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from .models import ModelBundle


def global_permutation_importance(
    bundle: ModelBundle,
    features: pd.DataFrame,
    targets: np.ndarray | pd.Series,
    *,
    repeats: int = 8,
    random_state: int = 42,
) -> list[dict[str, float | str | bool]]:
    """Rank predictive associations by MAE degradation under permutation."""

    X = features[bundle.feature_names]
    y = np.asarray(targets, dtype=float)
    result = permutation_importance(
        bundle.model,
        X,
        y,
        scoring="neg_mean_absolute_error",
        n_repeats=repeats,
        random_state=random_state,
        n_jobs=1,
    )
    ranking = sorted(
        zip(bundle.feature_names, result.importances_mean, result.importances_std, strict=True),
        key=lambda item: abs(float(item[1])),
        reverse=True,
    )
    return [
        {
            "feature": name,
            "importance": float(mean),
            "std": float(std),
            **_association_semantics(name),
        }
        for name, mean, std in ranking
    ]


def local_driver_analysis(
    bundle: ModelBundle,
    row: pd.DataFrame,
    reference: pd.DataFrame | None = None,
    *,
    baseline: pd.Series | None = None,
    limit: int = 10,
) -> list[dict[str, float | str | bool]]:
    """Explain associations with one vectorized perturbation prediction call."""

    current = row[bundle.feature_names].tail(1).copy()
    if baseline is None:
        if reference is None:
            raise ValueError("reference or precomputed baseline is required")
        baseline = reference[bundle.feature_names].median(numeric_only=True)
    perturbations = _perturbation_frame(current, bundle.feature_names, baseline)
    predictions = np.asarray(bundle.predict(perturbations), dtype=float)
    return _drivers_from_predictions(
        current,
        bundle.feature_names,
        predictions,
        limit,
    )


def local_driver_analysis_many(
    bundle: ModelBundle,
    rows: pd.DataFrame,
    *,
    baseline: pd.Series,
    key_column: str = "territory_id",
    limit: int = 10,
    chunk_size: int = 64,
) -> dict[str, list[dict[str, float | str | bool]]]:
    """Explain many rows with one model call per bounded territory chunk."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if key_column not in rows.columns:
        raise KeyError(key_column)
    keys = rows[key_column].astype(str)
    if keys.duplicated().any():
        raise ValueError(f"{key_column} must be unique for batched explanations")
    results: dict[str, list[dict[str, float | str | bool]]] = {}
    block_size = len(bundle.feature_names) + 1
    for start in range(0, len(rows), chunk_size):
        chunk = rows.iloc[start : start + chunk_size]
        perturbation_blocks = []
        current_rows = []
        for _, item in chunk.iterrows():
            current = item.to_frame().T[bundle.feature_names].copy()
            current_rows.append(current)
            perturbation_blocks.append(_perturbation_frame(current, bundle.feature_names, baseline))
        if not perturbation_blocks:
            continue
        predictions = np.asarray(
            bundle.predict(pd.concat(perturbation_blocks, ignore_index=True)),
            dtype=float,
        )
        if len(predictions) != len(chunk) * block_size:
            raise ValueError("Model returned an unexpected batched explanation shape")
        for offset, (key, current) in enumerate(
            zip(chunk[key_column].astype(str), current_rows, strict=True)
        ):
            first = offset * block_size
            results[key] = _drivers_from_predictions(
                current,
                bundle.feature_names,
                predictions[first : first + block_size],
                limit,
            )
    return results


def _perturbation_frame(
    current: pd.DataFrame,
    feature_names: list[str],
    baseline: pd.Series,
) -> pd.DataFrame:
    perturbations = pd.concat(
        [current] * (len(feature_names) + 1),
        ignore_index=True,
    )
    for index, feature in enumerate(feature_names, start=1):
        perturbations.loc[index, feature] = baseline.get(feature, np.nan)
    return perturbations


def _drivers_from_predictions(
    current: pd.DataFrame,
    feature_names: list[str],
    predictions: np.ndarray,
    limit: int,
) -> list[dict[str, float | str | bool]]:
    original = float(predictions[0])
    drivers: list[dict[str, float | str | bool]] = []
    for index, feature in enumerate(feature_names, start=1):
        drivers.append(
            {
                "feature": feature,
                "contribution": original - float(predictions[index]),
                "value": float(current[feature].iloc[0])
                if pd.notna(current[feature].iloc[0])
                else float("nan"),
                **_association_semantics(feature),
            }
        )
    return sorted(drivers, key=lambda item: abs(float(item["contribution"])), reverse=True)[:limit]


def _association_semantics(feature: str) -> dict[str, str | bool]:
    semantics: dict[str, str | bool] = {
        "causal_interpretation": False,
        "interpretation": "predictive_association_only",
    }
    if feature.startswith("pai_"):
        semantics["interpretation"] = "health_system_access_proxy_association_only"
    return semantics


def shap_values_optional(
    bundle: ModelBundle,
    rows: pd.DataFrame,
    *,
    background_rows: int = 50,
) -> dict[str, Any]:
    """Return SHAP values when the optional dependency is installed.

    This generic callable explainer supports the full stack, rather than only a
    single base model. It is intentionally opt-in because it can be expensive.
    """

    try:
        import shap
    except ImportError as exc:  # pragma: no cover - depends on optional extra.
        raise RuntimeError("Install the optional 'shap' package for SHAP explanations") from exc
    X = rows[bundle.feature_names]
    background = shap.sample(X, min(background_rows, len(X)), random_state=42)

    def predict(values: Any) -> np.ndarray:
        frame = pd.DataFrame(values, columns=bundle.feature_names)
        return bundle.predict(frame)

    explainer = shap.Explainer(predict, background)
    values = explainer(X)
    return {
        "feature_names": bundle.feature_names,
        "values": np.asarray(values.values).tolist(),
        "base_values": np.asarray(values.base_values).tolist(),
    }
