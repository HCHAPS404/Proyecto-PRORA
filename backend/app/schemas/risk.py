from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

Disease = Literal["dengue", "malaria", "chikunguna", "zika", "leishmaniasis", "ira"]


class ProvenanceSourceResponse(BaseModel):
    source_id: str
    name: str
    institution: str
    last_success_at: datetime | None = None


class AnalyticsSeriesPoint(BaseModel):
    week: date
    observed_cases: int
    population: int | None
    incidence_per_100k: float | None
    mean_quality_score: float | None
    is_preliminary: bool
    municipalities_with_notified_cases: int


class AnalyticsSeriesResponse(BaseModel):
    territory: str
    scope: Literal["national", "department", "municipality"]
    disease: Disease
    points: list[AnalyticsSeriesPoint]
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalyticsWindowAggregate(BaseModel):
    """Observed-case aggregate over a bounded calendar window.

    Weeks without a published observation are reported as missing instead of
    being silently converted to zero cases.
    """

    weeks: Literal[4, 12]
    from_week: date
    to_week: date
    observed_cases: int
    observed_week_count: int
    missing_week_count: int
    previous_observed_cases: int | None = None
    previous_observed_week_count: int
    previous_missing_week_count: int
    comparable: bool
    percent_change_vs_previous: float | None = None
    incidence_per_100k: float | None = None


class AnalyticsSummaryResponse(BaseModel):
    territory: str
    scope: Literal["national", "department", "municipality"]
    disease: Disease
    latest: AnalyticsSeriesPoint | None
    previous: AnalyticsSeriesPoint | None
    absolute_change: int | None
    percent_change: float | None
    comparison_gap_days: int | None
    comparison_gap_weeks: float | None
    comparison_comparable: bool
    data_status: Literal["no_data", "fresh", "stale"]
    observation_age_days: int | None
    sources: list[ProvenanceSourceResponse]
    population_denominator: dict[str, Any] = Field(default_factory=dict)
    windows: list[AnalyticsWindowAggregate] = Field(default_factory=list)


class CurrentOfficialReferenceResponse(BaseModel):
    requested_territory: str
    reference_territory_code: str
    reference_territory_name: str
    reference_territory_level: Literal["national", "department", "district"]
    geographic_context_only: bool
    disease: Disease
    event_label: str
    epidemiological_year: int
    epidemiological_week: int
    period_start: date
    period_end: date
    cumulative_cases: int
    expected_cases: int | None
    observed_cases: int | None
    comparison_basis: str
    is_preliminary: bool
    data_status: Literal["current", "stale"]
    age_days: int
    source_name: str
    source_document_url: str
    source_page: int
    limitations: list[str] = Field(default_factory=list)


class AnalyticsForecastPoint(BaseModel):
    target_week: date
    predicted_cases: float
    lower_bound: float
    upper_bound: float
    max_outbreak_probability: float
    component_predictions: dict[str, float]
    municipalities: int
    model_version: str


class AnalyticsForecastSeriesResponse(BaseModel):
    territory: str
    scope: Literal["national", "department", "municipality"]
    disease: Disease
    horizon: int
    points: list[AnalyticsForecastPoint]
    metadata: dict[str, Any] = Field(default_factory=dict)


class HistoricalTerritoryItemResponse(BaseModel):
    cod_dane: str
    municipality: str
    department_code: str
    department: str
    population: int | None
    latitude: float | None
    longitude: float | None
    first_week: date
    latest_week: date
    observation_rows: int
    total_observed_cases: int
    latest_observed_cases: int
    latest_is_preliminary: bool
    latest_quality_score: float


class HistoricalTerritoriesResponse(BaseModel):
    disease: Disease
    total: int
    items: list[HistoricalTerritoryItemResponse]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskMapItem(BaseModel):
    cod_dane: str
    municipality: str
    department: str
    disease: Disease
    horizon: int
    risk_score: float
    risk_level: Literal["bajo", "moderado", "alto", "critico"]
    expected_cases: float
    lower_bound: float
    upper_bound: float
    population: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    target_week: date
    updated_at: datetime
    model_version: str
    data_completeness: float
    observation_cutoff: date | None = None
    observation_age_days: int | None = None
    operationally_eligible: bool = True


class HistoricalPointResponse(BaseModel):
    date: date
    epidemiological_week: int
    observed: int
    predicted: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    is_preliminary: bool
    quality_score: float


class ExplanationResponse(BaseModel):
    forecast_id: str
    cod_dane: str
    disease: Disease
    horizon: int
    risk_score: float
    drivers: list[dict[str, Any]]
    component_predictions: dict[str, Any]
    warnings: list[str]
    model_version: str
    observation_cutoff: date | None = None
    operationally_eligible: bool = True
    probability_calibration: dict[str, Any] = Field(default_factory=dict)


class ModelMetadataResponse(BaseModel):
    disease: Disease
    horizon: int
    version: str
    status: str
    trained_at: datetime
    activated_at: datetime | None
    metrics: dict[str, Any]
    features: list[str]
    training_period: dict[str, date | None]
    data_fingerprint: str | None = None
    artifact_sha256: str | None = None
    pipeline_fingerprint: str | None = None


class ModelVersionSummary(BaseModel):
    disease: Disease
    horizon: int
    version: str
    stage: str
    created_at: datetime
    activated_at: datetime | None
    data_fingerprint: str | None
    artifact_sha256: str | None
    temporal_mae: float | None = None
    territorial_mae: float | None = None


class ModelTraceResponse(BaseModel):
    disease: Disease
    horizon: int
    version: str
    stage: str
    artifact_ref: str
    artifact_sha256: str
    artifact_integrity_valid: bool
    data_fingerprint: str | None
    dataset_snapshot_sha256: str | None
    pipeline_fingerprint: str | None
    training_job_id: str | None
    seed: int | None
    parameters: dict[str, Any]
    runtime: dict[str, Any]
    metrics: dict[str, Any]
    fold_metrics: list[dict[str, Any]]
    dataset: dict[str, Any]
    readiness: dict[str, Any] = Field(default_factory=dict)
    features: list[str]
    training_period: dict[str, date | None]
    created_at: datetime
    activated_at: datetime | None


class ModelPortfolioReadinessResponse(BaseModel):
    generated_at: datetime
    policy: dict[str, Any]
    diseases: list[dict[str, Any]]
    covariate_inventory: dict[str, Any]


class ModelActivationResponse(BaseModel):
    disease: Disease
    horizon: int
    version: str
    stage: Literal["champion"]
    activated_at: datetime


class TrainingRequest(BaseModel):
    disease: Disease
    horizons: list[int] = Field(default_factory=lambda: [3, 4], min_length=1, max_length=2)
    force: bool = False


class TrainingJobResponse(BaseModel):
    # Request handlers build this response with ``job_id`` while ORM-backed
    # status reads expose the primary key as ``id``. Keep one public contract
    # and accept both input shapes without leaking an internal field name.
    job_id: str = Field(validation_alias=AliasChoices("job_id", "id"))
    disease: str
    horizons: list[int]
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class AlertEventResponse(BaseModel):
    id: str
    forecast_id: str
    cod_dane: str
    municipality: str
    department: str
    disease: Disease
    horizon: int
    risk_score: float
    risk_level: str
    predicted_cases: float
    lower_bound: float
    upper_bound: float
    drivers: list[dict[str, Any]]
    status: str
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None
    created_at: datetime
    issued_at: datetime
    target_week: date
    operationally_eligible: bool


class AlertReviewRequest(BaseModel):
    status: Literal["acknowledged", "closed", "false_positive"]
    notes: str = Field(min_length=3, max_length=2000)
