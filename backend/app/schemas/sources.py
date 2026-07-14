from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DatasetType = Literal[
    "epidemiology",
    "climate",
    "vaccination",
    "deforestation",
    "socioeconomic",
]


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    institution: str
    source_type: str
    endpoint: str | None
    dataset_id: str | None
    status: str
    is_public: bool
    refresh_cron: str | None
    configuration: dict[str, Any]
    last_checked_at: datetime | None
    last_success_at: datetime | None


class IngestionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    rows_read: int
    rows_accepted: int
    rows_rejected: int
    checksum: str | None
    cursor: str | None
    provenance: dict[str, Any]
    quality_report: dict[str, Any]
    error_message: str | None

    @field_validator("provenance")
    @classmethod
    def redact_internal_paths(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Never disclose worker filesystem paths through the public runs API."""
        allowed = {
            "kind",
            "request",
            "snapshot_sha256",
            "schema_sha256",
            "dataset_type",
            "original_filename",
            "content_bytes",
        }
        return {key: item for key, item in value.items() if key in allowed}


class SourceSyncRequest(BaseModel):
    mode: Literal["incremental", "backfill"] = "incremental"
    from_date: date | None = None
    to_date: date | None = None
    max_records: int | None = Field(default=None, ge=1, le=1_000_000)
    event_codes: list[int] | None = Field(default=None, min_length=1, max_length=25)

    @field_validator("event_codes")
    @classmethod
    def validate_event_codes(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(code < 1 or code > 999 for code in value):
            raise ValueError("event_codes debe contener codigos INS entre 1 y 999")
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_window(self) -> SourceSyncRequest:
        if self.mode == "backfill" and (self.from_date is None or self.to_date is None):
            raise ValueError("backfill requiere from_date y to_date")
        if self.from_date and self.to_date and self.from_date >= self.to_date:
            raise ValueError("from_date debe ser anterior a to_date")
        return self


class StoredDatasetInventory(BaseModel):
    source_id: str
    source_name: str
    catalog_status: str
    sync_enabled: bool
    canonical_table: str
    rows: int
    has_stored_data: bool
    storage_status: Literal["empty", "raw_only", "canonical"]
    raw_snapshot_count: int
    territorial_resolution: str
    temporal_resolution: str
    period_start: date | None
    period_end: date | None
    last_ingestion_at: datetime | None
    last_snapshot_sha256: str | None
    quality_status: str | None
    rows_rejected_last_run: int
    semantics: str


class DiseaseDataCoverage(BaseModel):
    """Public, evidence-backed availability for one prioritised disease.

    Historical observations, registered models and operational forecasts are
    deliberately separate.  Consumers must not infer that a trained model is
    suitable for current alerts when its epidemiological cut-off is stale.
    """

    disease: Literal["dengue", "malaria", "chikunguna", "zika", "leishmaniasis", "ira"]
    observation_status: Literal["no_data", "historical", "current"]
    observation_rows: int
    observed_cases: int
    municipalities_with_observations: int
    period_start: date | None
    period_end: date | None
    observation_age_days: int | None
    source_ids: list[str]
    champion_model_horizons: list[int]
    historical_forecasts: int
    operational_forecasts: int
    open_operational_alerts: int
    operational_ready: bool
    blocking_reasons: list[
        Literal[
            "no_observations",
            "epidemiological_cutoff_is_historical",
            "no_champion_model",
            "no_operational_forecasts",
        ]
    ]


class SnapshotManifestResponse(BaseModel):
    ingestion_run_id: str
    source_id: str
    object_sha256: str
    manifest: dict[str, Any]
