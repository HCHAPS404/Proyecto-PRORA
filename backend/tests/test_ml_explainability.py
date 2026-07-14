from __future__ import annotations

import numpy as np
import pandas as pd

from app.jobs.training import _drivers_for_horizon
from app.ml.explainability import local_driver_analysis, local_driver_analysis_many


class _CountingBundle:
    feature_names = ["a", "b", "c"]
    disease = "dengue"

    def __init__(self) -> None:
        self.calls = 0
        self.predicted_rows = 0

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        self.calls += 1
        self.predicted_rows += len(frame)
        return frame[self.feature_names].sum(axis=1).to_numpy(dtype=float)


def test_local_driver_analysis_vectorizes_all_feature_perturbations() -> None:
    bundle = _CountingBundle()
    row = pd.DataFrame([{"a": 10.0, "b": 20.0, "c": 30.0}])
    baseline = pd.Series({"a": 1.0, "b": 2.0, "c": 3.0})

    drivers = local_driver_analysis(bundle, row, baseline=baseline, limit=3)

    assert bundle.calls == 1
    assert bundle.predicted_rows == 4  # original + one perturbation per feature
    assert [item["feature"] for item in drivers] == ["c", "b", "a"]
    assert [item["contribution"] for item in drivers] == [27.0, 18.0, 9.0]
    assert all(item["causal_interpretation"] is False for item in drivers)


def test_multi_territory_explanations_equal_individual_results_and_preserve_order() -> None:
    rows = pd.DataFrame(
        [
            {
                "territory_id": f"{index:05d}",
                "disease": "dengue",
                "a": 10.0 + index,
                "b": 20.0 + index,
                "c": 30.0 + index,
            }
            for index in range(5)
        ]
    )
    baseline = pd.Series({"a": 1.0, "b": 2.0, "c": 3.0})
    individual_bundle = _CountingBundle()
    expected = {
        row["territory_id"]: local_driver_analysis(
            individual_bundle,
            pd.DataFrame([row]),
            baseline=baseline,
            limit=3,
        )
        for row in rows.to_dict(orient="records")
    }

    batch_bundle = _CountingBundle()
    actual = local_driver_analysis_many(
        batch_bundle,
        rows,
        baseline=baseline,
        chunk_size=2,
        limit=3,
    )

    assert list(actual) == rows["territory_id"].tolist()
    assert actual == expected
    assert batch_bundle.calls == 3
    assert batch_bundle.predicted_rows == len(rows) * 4


class _FailingTerritoryBundle(_CountingBundle):
    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if (frame["a"] < 0).any():
            raise ValueError("invalid territory row")
        return super().predict(frame)


def test_chunk_failure_falls_back_and_marks_only_the_invalid_territory() -> None:
    rows = pd.DataFrame(
        [
            {"territory_id": "05001", "disease": "dengue", "a": 10, "b": 20, "c": 30},
            {"territory_id": "05002", "disease": "dengue", "a": -1, "b": 20, "c": 30},
            {"territory_id": "05003", "disease": "dengue", "a": 12, "b": 22, "c": 32},
        ]
    )
    baseline = pd.Series({"a": 1.0, "b": 2.0, "c": 3.0})

    result = _drivers_for_horizon(
        _FailingTerritoryBundle(),
        rows,
        baseline,
        chunk_size=2,
    )

    assert list(result) == ["05001", "05002", "05003"]
    assert result["05001"][0] and result["05001"][1] is None
    assert result["05002"] == ([], "explanation_unavailable")
    assert result["05003"][0] and result["05003"][1] is None
