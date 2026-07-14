"""Configuration shared by feature, training and inference pipelines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DISEASES: tuple[str, ...] = (
    "dengue",
    "malaria",
    "chikunguna",
    "zika",
    "leishmaniasis",
    "ira",
)


@dataclass(frozen=True, slots=True)
class MLConfig:
    """Reproducible training configuration.

    ``enable_lstm`` enables a real PyTorch LSTM when PyTorch is available.  If
    it is not installed, the temporal learner deterministically falls back to
    Ridge regression, keeping local and CI deployments lightweight.
    """

    date_column: str = "week"
    target_column: str = "cases"
    disease_column: str = "disease"
    territory_column: str = "territory_id"
    lags: tuple[int, ...] = tuple(range(1, 13))
    rolling_windows: tuple[int, ...] = (2, 4, 8, 12)
    horizons: tuple[int, ...] = (3, 4)
    min_train_weeks: int = 52
    validation_weeks: int = 4
    n_splits: int = 4
    territorial_splits: int = 3
    # Leave-department-out already provides the outer generalisation test.  A
    # single chronological meta holdout inside each outer fold keeps the full
    # stack honest without multiplying the training cost by every temporal
    # fold again.
    territorial_meta_splits: int = 1
    outbreak_quantile: float = 0.80
    conformal_alpha: float = 0.10
    max_forecast_data_age_days: int = 35
    min_observed_training_rows: int = 500
    min_training_territories: int = 20
    min_training_weeks: int = 104
    min_reporting_density: float = 0.10
    random_state: int = 42
    enable_lstm: bool = True
    lstm_epochs: int = 35
    lstm_hidden_size: int = 24
    rf_estimators: int = 160
    hgb_iterations: int = 140
    known_exogenous: tuple[str, ...] = (
        "precipitation",
        "temperature",
        "humidity",
        "pai_health_system_access_proxy",
        "deforestation",
        "water_access",
        "sewer_access",
        "overcrowding",
        "nbi",
        "urban_population_pct",
        "rural_population_pct",
        "population",
    )
    diseases: tuple[str, ...] = field(default=DISEASES)

    def validate(self) -> None:
        if not self.lags or min(self.lags) < 1:
            raise ValueError("lags must contain positive integers")
        if not 0 < self.outbreak_quantile < 1:
            raise ValueError("outbreak_quantile must be between 0 and 1")
        if not 0 < self.conformal_alpha < 1:
            raise ValueError("conformal_alpha must be between 0 and 1")
        if min(self.horizons) < 1:
            raise ValueError("forecast horizons must be positive")
        if self.territorial_splits < 2:
            raise ValueError("territorial_splits must be at least 2")
        if self.territorial_meta_splits < 1:
            raise ValueError("territorial_meta_splits must be at least 1")
        if self.max_forecast_data_age_days < 1:
            raise ValueError("max_forecast_data_age_days must be positive")
        if self.min_observed_training_rows < 1:
            raise ValueError("min_observed_training_rows must be positive")
        if self.min_training_territories < 1 or self.min_training_weeks < 2:
            raise ValueError("training coverage thresholds must be positive")
        if not 0 < self.min_reporting_density <= 1:
            raise ValueError("min_reporting_density must be between 0 and 1")

    def assert_disease(self, disease: str) -> str:
        normalized = normalize_disease(disease)
        if normalized not in self.diseases:
            raise ValueError(
                f"Unsupported disease '{disease}'. Expected one of: " + ", ".join(self.diseases)
            )
        return normalized

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_disease(value: str) -> str:
    """Normalize common labels while keeping one canonical storage key."""

    normalized = value.strip().lower().replace(" ", "_")
    aliases = {
        "chikunguña": "chikunguna",
        "chikungunya": "chikunguna",
        "infeccion_respiratoria_aguda": "ira",
        "infecciones_respiratorias_agudas": "ira",
    }
    return aliases.get(normalized, normalized)
