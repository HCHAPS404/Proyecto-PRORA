"""Chronology-preserving validation utilities."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pandas as pd

from .metrics import regression_and_outbreak_metrics


def expanding_window_splits(
    dates: pd.Series | np.ndarray,
    *,
    min_train_periods: int = 52,
    validation_periods: int = 4,
    n_splits: int = 4,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield expanding train/validation indices based on unique weeks.

    Multiple territories belonging to a week are always kept in the same fold,
    preventing a future municipality from leaking into another municipality's
    training block.
    """

    values = pd.to_datetime(pd.Series(dates), errors="raise")
    unique = np.asarray(sorted(values.unique()))
    if len(unique) < min_train_periods + validation_periods:
        raise ValueError(
            "Not enough unique weeks for temporal validation: "
            f"received {len(unique)}, need at least {min_train_periods + validation_periods}"
        )

    possible_starts = list(
        range(min_train_periods, len(unique) - validation_periods + 1, validation_periods)
    )
    selected = possible_starts[-n_splits:]
    for start in selected:
        train_weeks = unique[:start]
        valid_weeks = unique[start : start + validation_periods]
        train_idx = np.flatnonzero(values.isin(train_weeks).to_numpy())
        valid_idx = np.flatnonzero(values.isin(valid_weeks).to_numpy())
        if len(train_idx) and len(valid_idx):
            yield train_idx, valid_idx


def territorial_group_splits(
    territories: pd.Series | np.ndarray,
    *,
    n_splits: int = 3,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield deterministic leave-region-out folds.

    DIVIPOLA's first two digits identify a department. For non-DIVIPOLA keys,
    the complete key becomes the group. No municipality from a held-out region
    is present in that fold's training set.
    """

    values = pd.Series(territories).astype(str).reset_index(drop=True)
    regions = values.map(lambda value: value[:2] if len(value) >= 2 else value)
    unique_regions = sorted(regions.unique().tolist())
    if len(unique_regions) < 2:
        return
    fold_count = min(max(2, n_splits), len(unique_regions))
    assignments = {region: index % fold_count for index, region in enumerate(unique_regions)}
    for fold in range(fold_count):
        validation_mask = regions.map(assignments).eq(fold).to_numpy()
        validation_idx = np.flatnonzero(validation_mask)
        train_idx = np.flatnonzero(~validation_mask)
        if len(train_idx) and len(validation_idx):
            yield train_idx, validation_idx


def temporal_cross_validate(
    estimator_factory: Callable[[], Any],
    X: pd.DataFrame,
    y: pd.Series | np.ndarray,
    dates: pd.Series | np.ndarray,
    *,
    min_train_periods: int = 52,
    validation_periods: int = 4,
    n_splits: int = 4,
    outbreak_threshold: float | None = None,
) -> tuple[list[dict[str, float]], np.ndarray]:
    """Evaluate a model and return fold metrics plus aligned OOF predictions."""

    targets = np.asarray(y, dtype=float)
    oof = np.full(len(targets), np.nan, dtype=float)
    reports: list[dict[str, float]] = []
    for fold, (train_idx, valid_idx) in enumerate(
        expanding_window_splits(
            dates,
            min_train_periods=min_train_periods,
            validation_periods=validation_periods,
            n_splits=n_splits,
        ),
        start=1,
    ):
        estimator = estimator_factory()
        estimator.fit(X.iloc[train_idx], targets[train_idx])
        predictions = np.maximum(0.0, np.asarray(estimator.predict(X.iloc[valid_idx]), dtype=float))
        oof[valid_idx] = predictions
        threshold = (
            float(outbreak_threshold)
            if outbreak_threshold is not None
            else float(np.quantile(targets[train_idx], 0.80))
        )
        metrics = regression_and_outbreak_metrics(targets[valid_idx], predictions, threshold)
        metrics["fold"] = float(fold)
        metrics["train_rows"] = float(len(train_idx))
        metrics["validation_rows"] = float(len(valid_idx))
        reports.append(metrics)
    return reports, oof
