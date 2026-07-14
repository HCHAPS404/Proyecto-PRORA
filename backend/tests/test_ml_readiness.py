from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.ml.config import MLConfig
from app.ml.readiness import assess_training_frame


def _frame(*, explicit_zeros: bool) -> pd.DataFrame:
    end = date.today() - timedelta(days=(date.today().weekday() + 1) % 7)
    weeks = pd.date_range(end=end, periods=110, freq="7D")
    rows = []
    for territory_index in range(2):
        for index, week in enumerate(weeks):
            cases = 0 if explicit_zeros and index % 7 == 0 else 2 + territory_index
            if not explicit_zeros and index % 3 == 0:
                cases = None
            rows.append(
                {
                    "week": week,
                    "disease": "dengue",
                    "territory_id": f"05{territory_index:03d}",
                    "cases": cases,
                }
            )
    return pd.DataFrame(rows)


def test_positive_only_notifications_are_never_operationally_eligible() -> None:
    config = MLConfig(
        min_observed_training_rows=100,
        min_training_territories=2,
        min_training_weeks=100,
        min_reporting_density=0.5,
    )
    readiness = assess_training_frame(_frame(explicit_zeros=False), "dengue", config)
    assert readiness["research_training_eligible"] is True
    assert readiness["operational_forecast_eligible"] is False
    assert readiness["readiness_level"] == "research_only"
    assert readiness["explicit_zero_case_rows"] == 0
    assert any(item["code"] == "no_explicit_zero_case_reports" for item in readiness["limitations"])


def test_complete_recent_panel_can_pass_operational_data_gate() -> None:
    config = MLConfig(
        min_observed_training_rows=100,
        min_training_territories=2,
        min_training_weeks=100,
        min_reporting_density=0.5,
    )
    readiness = assess_training_frame(_frame(explicit_zeros=True), "dengue", config)
    assert readiness["operational_forecast_eligible"] is True
    assert readiness["readiness_level"] == "operational"
    assert readiness["explicit_zero_case_rows"] > 0


def test_low_reporting_density_allows_research_but_blocks_operations() -> None:
    config = MLConfig(
        min_observed_training_rows=100,
        min_training_territories=2,
        min_training_weeks=100,
        min_reporting_density=0.8,
    )
    readiness = assess_training_frame(_frame(explicit_zeros=False), "zika", config)
    assert readiness["requirements"]["reporting_density"]["passes"] is False
    assert readiness["research_training_eligible"] is True
    assert readiness["operational_forecast_eligible"] is False
    assert readiness["readiness_level"] == "research_only"
    assert any(
        item["code"] == "low_reporting_density"
        for item in readiness["limitations"]
    )
