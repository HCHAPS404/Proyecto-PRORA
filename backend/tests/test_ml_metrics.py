from __future__ import annotations

import numpy as np

from app.ml.metrics import regression_and_outbreak_metrics


def test_auc_uses_margin_over_row_specific_outbreak_threshold() -> None:
    truth = np.asarray([110.0, 90.0, 15.0, 5.0])
    prediction = np.asarray([105.0, 95.0, 12.0, 9.0])
    thresholds = np.asarray([100.0, 100.0, 10.0, 10.0])

    metrics = regression_and_outbreak_metrics(truth, prediction, thresholds)

    # Raw predicted counts would rank one low-baseline outbreak below a
    # high-baseline non-outbreak (AUC 0.75). Margins rank both correctly.
    assert metrics["auc"] == 1.0
