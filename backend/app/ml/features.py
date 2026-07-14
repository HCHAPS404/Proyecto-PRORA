"""Leakage-safe weekly feature engineering for epidemiological panels."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from .config import MLConfig, normalize_disease

REQUIRED_COLUMNS = ("week", "disease", "territory_id", "cases")


def normalize_weekly_frame(data: pd.DataFrame, config: MLConfig | None = None) -> pd.DataFrame:
    """Validate and normalize a public-health panel to one row per week/key.

    Duplicate case records are summed. Environmental and coverage variables are
    averaged, while deforestation is summed because it normally represents an
    area increment. The function does *not* invent missing epidemiological
    weeks; absence can mean delayed reporting and must be handled upstream.
    """

    cfg = config or MLConfig()
    cfg.validate()
    required = {
        cfg.date_column,
        cfg.disease_column,
        cfg.territory_column,
        cfg.target_column,
    }
    missing = sorted(required.difference(data.columns))
    if missing:
        raise ValueError(f"Missing required ML columns: {', '.join(missing)}")
    if data.empty:
        raise ValueError("Training data is empty")

    frame = data.copy()
    parsed = pd.to_datetime(frame[cfg.date_column], errors="coerce", utc=True)
    if parsed.isna().any():
        bad = int(parsed.isna().sum())
        raise ValueError(f"{bad} rows have invalid week values")
    # INS surveillance weeks run Sunday through Saturday. W-SAT therefore
    # normalizes any date to the official Sunday start without timezone noise.
    frame[cfg.date_column] = parsed.dt.tz_convert(None).dt.to_period("W-SAT").dt.start_time
    frame[cfg.disease_column] = frame[cfg.disease_column].astype(str).map(normalize_disease)
    frame[cfg.territory_column] = frame[cfg.territory_column].astype(str).str.strip()
    raw_target = frame[cfg.target_column]
    numeric_target = pd.to_numeric(raw_target, errors="coerce")
    if (raw_target.notna() & numeric_target.isna()).any():
        raise ValueError("non-null cases values must be numeric")
    frame[cfg.target_column] = numeric_target
    if (numeric_target.dropna() < 0).any():
        raise ValueError("cases cannot be negative")

    keys = [cfg.disease_column, cfg.territory_column, cfg.date_column]
    if frame.duplicated(keys).any():
        aggregations: dict[str, Any] = {cfg.target_column: lambda values: values.sum(min_count=1)}
        for column in frame.columns:
            if column in keys or column == cfg.target_column:
                continue
            if pd.api.types.is_numeric_dtype(frame[column]):
                aggregations[column] = "sum" if column == "deforestation" else "mean"
            else:
                aggregations[column] = "last"
        frame = frame.groupby(keys, as_index=False, observed=True).agg(aggregations)

    return frame.sort_values(keys).reset_index(drop=True)


def build_weekly_features(data: pd.DataFrame, config: MLConfig | None = None) -> pd.DataFrame:
    """Create weekly lags, rolling summaries, seasonality and domain signals.

    All target-derived aggregates are shifted by one week. Consequently a row
    at week *t* never uses cases from week *t* or the future, except for the
    explicit ``cases_current`` feature, which represents information observed
    at forecast issuance time.
    """

    cfg = config or MLConfig()
    frame = _regularize_calendar(normalize_weekly_frame(data, cfg), cfg)
    keys = [cfg.disease_column, cfg.territory_column]
    grouped_cases = frame.groupby(keys, sort=False, observed=True)[cfg.target_column]

    frame["cases_current"] = frame[cfg.target_column].astype(float)
    for lag in cfg.lags:
        frame[f"cases_lag_{lag}"] = grouped_cases.shift(lag)

    for window in cfg.rolling_windows:
        frame[f"cases_roll_mean_{window}"] = grouped_cases.transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=max(2, w // 2)).mean()
        )
        frame[f"cases_roll_sum_{window}"] = grouped_cases.transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=max(2, w // 2)).sum()
        )
        frame[f"cases_roll_std_{window}"] = grouped_cases.transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=max(2, w // 2)).std()
        )

    frame["territory_historical_mean"] = grouped_cases.transform(
        lambda values: values.shift(1).expanding(min_periods=4).mean()
    )
    frame["territory_historical_std"] = grouped_cases.transform(
        lambda values: values.shift(1).expanding(min_periods=6).std()
    )
    frame["outbreak_threshold"] = grouped_cases.transform(
        lambda values: values.shift(1).rolling(52, min_periods=12).quantile(cfg.outbreak_quantile)
    )

    iso_week = frame[cfg.date_column].dt.isocalendar().week.astype(float)
    angle = 2.0 * np.pi * iso_week / 52.1775
    frame["week_sin"] = np.sin(angle)
    frame["week_cos"] = np.cos(angle)
    first_year = frame[cfg.date_column].dt.year.min()
    frame["year_trend"] = (frame[cfg.date_column].dt.year - first_year).astype(float)

    for column in ("precipitation", "temperature", "humidity"):
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        frame[column] = values
        grouped = frame.groupby(keys, sort=False, observed=True)[column]
        baseline = grouped.transform(lambda x: x.shift(1).rolling(12, min_periods=4).mean())
        spread = grouped.transform(lambda x: x.shift(1).rolling(12, min_periods=4).std())
        frame[f"{column}_anomaly"] = (values - baseline) / spread.replace(0, np.nan)
        frame[f"{column}_lag_1"] = grouped.shift(1)
        frame[f"{column}_roll_mean_4"] = grouped.transform(
            lambda x: x.rolling(4, min_periods=2).mean()
        )

    if "pai_health_system_access_proxy" in frame.columns:
        coverage = pd.to_numeric(frame["pai_health_system_access_proxy"], errors="coerce")
        # PAI program coverage is used only as a health-system access proxy,
        # never as disease-specific vaccine protection. Accept proportions or
        # percentages while keeping the engineered representation in percent.
        finite_median = coverage.dropna().median()
        if pd.notna(finite_median) and finite_median <= 1.5:
            coverage = coverage * 100.0
        frame["pai_health_system_access_proxy"] = coverage
        frame["pai_access_proxy_shortfall"] = (100.0 - coverage).clip(lower=0, upper=100)
        grouped = frame.groupby(keys, sort=False, observed=True)["pai_health_system_access_proxy"]
        frame["pai_access_proxy_change_4"] = coverage - grouped.shift(4)

    if "deforestation" in frame.columns:
        frame["deforestation"] = pd.to_numeric(frame["deforestation"], errors="coerce")
        grouped = frame.groupby(keys, sort=False, observed=True)["deforestation"]
        frame["deforestation_roll_sum_4"] = grouped.transform(
            lambda x: x.rolling(4, min_periods=1).sum()
        )
        frame["deforestation_change_12"] = frame["deforestation"] - grouped.shift(12)

    # Coerce configured exogenous inputs so the estimator receives a purely
    # numeric matrix and missingness is handled by its median imputer.
    for column in cfg.known_exogenous:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame.replace([np.inf, -np.inf], np.nan)


def _regularize_calendar(frame: pd.DataFrame, config: MLConfig) -> pd.DataFrame:
    pieces = []
    keys = [config.disease_column, config.territory_column]
    for (disease, territory), group in frame.groupby(keys, observed=True, sort=True):
        indexed = group.set_index(config.date_column).sort_index()
        calendar = pd.date_range(indexed.index.min(), indexed.index.max(), freq="7D")
        regular = indexed.reindex(calendar)
        regular.index.name = config.date_column
        regular[config.disease_column] = disease
        regular[config.territory_column] = territory
        pieces.append(regular.reset_index())
    return pd.concat(pieces, ignore_index=True).sort_values([*keys, config.date_column])


def build_supervised_frame(
    data: pd.DataFrame,
    horizon: int,
    config: MLConfig | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return a feature frame with a future target for ``horizon`` weeks."""

    cfg = config or MLConfig()
    if horizon < 1:
        raise ValueError("horizon must be a positive number of weeks")
    frame = build_weekly_features(data, cfg)
    keys = [cfg.disease_column, cfg.territory_column]
    grouped = frame.groupby(keys, sort=False, observed=True)[cfg.target_column]
    target_name = f"target_cases_h{horizon}"
    frame[target_name] = grouped.shift(-horizon)
    frame[f"outbreak_h{horizon}"] = (frame[target_name] >= frame["outbreak_threshold"]).where(
        frame[target_name].notna() & frame["outbreak_threshold"].notna()
    )

    excluded = {
        cfg.date_column,
        cfg.target_column,
        cfg.disease_column,
        cfg.territory_column,
        target_name,
        f"outbreak_h{horizon}",
    }
    features = [
        column
        for column in frame.columns
        if column not in excluded
        and not column.startswith("pai_program_coverage_")
        and pd.api.types.is_numeric_dtype(frame[column])
    ]
    if not features:
        raise ValueError("No numeric ML features could be generated")
    return frame, features


def latest_feature_rows(
    data: pd.DataFrame,
    feature_names: Iterable[str],
    config: MLConfig | None = None,
) -> pd.DataFrame:
    """Build the last inference row for every disease/territory series."""

    cfg = config or MLConfig()
    frame = build_weekly_features(data, cfg)
    keys = [cfg.disease_column, cfg.territory_column]
    latest = frame.groupby(keys, observed=True, sort=False).tail(1).copy()
    for column in feature_names:
        if column not in latest.columns:
            latest[column] = np.nan
    return latest[[*keys, cfg.date_column, *feature_names]]
