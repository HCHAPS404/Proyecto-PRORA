"""Metrics shared by offline validation and model metadata."""

from __future__ import annotations

import math

import numpy as np
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)


def regression_and_outbreak_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    outbreak_threshold: float | np.ndarray,
) -> dict[str, float]:
    """Compute regression and outbreak-detection metrics.

    A continuous outbreak score is derived from the predicted margin above the
    row-specific outbreak threshold. This keeps municipalities with different
    endemic baselines comparable without training a redundant classifier.
    """

    truth = np.asarray(y_true, dtype=float)
    prediction = np.asarray(y_pred, dtype=float)
    thresholds = np.asarray(outbreak_threshold, dtype=float)
    if thresholds.ndim == 0:
        thresholds = np.full(len(truth), float(thresholds), dtype=float)
    if len(thresholds) != len(truth):
        raise ValueError("outbreak_threshold must be scalar or aligned with observations")
    finite = np.isfinite(truth) & np.isfinite(prediction) & np.isfinite(thresholds)
    truth, prediction, thresholds = truth[finite], prediction[finite], thresholds[finite]
    if not len(truth):
        raise ValueError("Metrics require at least one finite observation")

    actual_event = truth >= thresholds
    predicted_event = prediction >= thresholds
    tp = int(np.sum(actual_event & predicted_event))
    tn = int(np.sum(~actual_event & ~predicted_event))
    fp = int(np.sum(~actual_event & predicted_event))
    fn = int(np.sum(actual_event & ~predicted_event))
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    if len(np.unique(actual_event)) == 2:
        outbreak_margin = prediction - thresholds
        auc = float(roc_auc_score(actual_event.astype(int), outbreak_margin))
    else:
        auc = math.nan

    return {
        "mae": float(mean_absolute_error(truth, prediction)),
        "rmse": float(mean_squared_error(truth, prediction) ** 0.5),
        "auc": auc,
        "sensitivity": float(sensitivity),
        "specificity": float(specificity),
        "observations": float(len(truth)),
    }


def aggregate_fold_metrics(reports: list[dict[str, float]]) -> dict[str, float]:
    """Average finite metrics across temporal folds."""

    if not reports:
        return {}
    aggregate: dict[str, float] = {}
    for key in ("mae", "rmse", "auc", "sensitivity", "specificity"):
        values = np.asarray([report.get(key, np.nan) for report in reports], dtype=float)
        finite = values[np.isfinite(values)]
        aggregate[key] = float(np.mean(finite)) if len(finite) else math.nan
    aggregate["folds"] = float(len(reports))
    return aggregate
