from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.config import MLConfig
from app.ml.features import build_supervised_frame, build_weekly_features
from app.ml.validation import expanding_window_splits


def _panel(weeks: int = 72) -> pd.DataFrame:
    rng = np.random.default_rng(20260712)
    rows = []
    dates = pd.date_range("2024-01-01", periods=weeks, freq="W-MON")
    for territory_index, territory in enumerate(("05001", "76001")):
        for index, week in enumerate(dates):
            seasonal = 8 * np.sin(2 * np.pi * index / 52)
            rain = 90 + 30 * np.sin(2 * np.pi * (index - 4) / 52)
            cases = max(0, 18 + 4 * territory_index + seasonal + 0.035 * rain + rng.normal(0, 2))
            rows.append(
                {
                    "week": week,
                    "disease": "dengue",
                    "territory_id": territory,
                    "cases": round(cases),
                    "precipitation": rain,
                    "temperature": 24 + territory_index + np.sin(index / 8),
                    "humidity": 72 + rain / 20,
                    "pai_health_system_access_proxy": 0.82 - index * 0.0005,
                    "deforestation": max(0, rng.normal(3 + territory_index, 0.4)),
                    "population": 500_000 + 100_000 * territory_index,
                }
            )
    return pd.DataFrame(rows)


def test_feature_engineering_contains_domain_and_temporal_signals() -> None:
    config = MLConfig(enable_lstm=False)
    engineered = build_weekly_features(_panel(), config)
    expected = {
        "cases_lag_1",
        "cases_lag_12",
        "cases_roll_sum_4",
        "week_sin",
        "week_cos",
        "precipitation_anomaly",
        "pai_access_proxy_shortfall",
        "pai_access_proxy_change_4",
        "deforestation_roll_sum_4",
    }
    assert expected.issubset(engineered.columns)
    assert engineered["pai_health_system_access_proxy"].median() > 50


def test_lag_is_not_contaminated_by_same_week_cases() -> None:
    data = _panel()
    baseline = build_weekly_features(data)
    changed = data.copy()
    row = changed.index[(changed["territory_id"] == "05001")][30]
    changed.loc[row, "cases"] += 1_000
    recomputed = build_weekly_features(changed)
    assert baseline.loc[row, "cases_lag_1"] == recomputed.loc[row, "cases_lag_1"]
    # The following week must observe the modified value, proving the lag is real.
    assert recomputed.loc[row + 1, "cases_lag_1"] - baseline.loc[row + 1, "cases_lag_1"] == 1_000


def test_supervised_target_and_temporal_splits_are_strictly_future() -> None:
    config = MLConfig(min_train_weeks=24, validation_weeks=4, n_splits=3, enable_lstm=False)
    frame, features = build_supervised_frame(_panel(), horizon=3, config=config)
    series = frame[frame["territory_id"] == "05001"].reset_index(drop=True)
    assert series.loc[10, "target_cases_h3"] == series.loc[13, "cases"]
    assert "target_cases_h3" not in features

    dates = frame[frame["target_cases_h3"].notna()]["week"].reset_index(drop=True)
    splits = list(
        expanding_window_splits(
            dates,
            min_train_periods=24,
            validation_periods=4,
            n_splits=3,
        )
    )
    assert len(splits) == 3
    for train, validation in splits:
        assert dates.iloc[train].max() < dates.iloc[validation].min()


def test_calendar_gaps_remain_missing_and_weeks_start_on_sunday() -> None:
    data = _panel(weeks=30)
    missing_week = data[(data["territory_id"] == "05001")].iloc[10]["week"]
    data = data[
        ~((data["territory_id"] == "05001") & (data["week"] == missing_week))
    ]
    engineered = build_weekly_features(data)
    territory = engineered[engineered["territory_id"] == "05001"].reset_index(drop=True)
    assert len(territory) == 30
    assert set(territory["week"].dt.dayofweek) == {6}
    gap = territory[territory["cases_current"].isna()].iloc[0]
    following = territory[territory["week"] == gap["week"] + pd.Timedelta(weeks=1)].iloc[0]
    assert pd.isna(following["cases_lag_1"])
