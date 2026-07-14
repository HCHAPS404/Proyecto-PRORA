"""Persisted public-health, provenance and prediction entities.

All epidemiological information is aggregated at municipality/week level.  No
patient identifiers belong in this schema.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.entities import new_id


class PipelineStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    REQUIRES_CONFIGURATION = "requires_configuration"
    DISABLED = "disabled"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    institution: Mapped[str] = mapped_column(String(160), index=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    endpoint: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40), default=SourceStatus.REQUIRES_CONFIGURATION.value, index=True
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_cron: Mapped[str | None] = mapped_column(String(80), nullable=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingestion_source_started", "source_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=PipelineStatus.PENDING.value, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cursor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    quality_report: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ingestion_run_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    object_path: Mapped[str] = mapped_column(String(1200))
    manifest_path: Mapped[str] = mapped_column(String(1200))
    media_type: Mapped[str] = mapped_column(String(100), default="application/x-ndjson")
    content_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    schema_sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuarantineRecord(Base):
    __tablename__ = "quarantine_records"
    __table_args__ = (
        Index("ix_quarantine_run_reason", "ingestion_run_id", "reason_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ingestion_run_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    raw_record_sha256: Mapped[str] = mapped_column(String(64), index=True)
    reason_code: Mapped[str] = mapped_column(String(80), index=True)
    reason: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Municipality(Base):
    __tablename__ = "municipalities"
    __table_args__ = (Index("ix_municipality_department_name", "department_code", "name"),)

    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    department_code: Mapped[str] = mapped_column(String(2), index=True)
    department_name: Mapped[str] = mapped_column(String(120), index=True)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_vintage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WeatherStation(Base):
    __tablename__ = "weather_stations"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(220))
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    technology: Mapped[str | None] = mapped_column(String(80), nullable=True)
    operational_status: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    department_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    municipality_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    municipality_code: Mapped[str | None] = mapped_column(
        ForeignKey("municipalities.code", ondelete="SET NULL"), nullable=True, index=True
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(220), nullable=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"))
    raw_record_sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EpidemiologicalObservation(Base):
    __tablename__ = "epidemiological_observations"
    __table_args__ = (
        UniqueConstraint(
            "municipality_code", "disease", "week_start", name="uq_epi_municipality_disease_week"
        ),
        Index("ix_epi_disease_week", "disease", "week_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code", ondelete="CASCADE"), index=True
    )
    disease: Mapped[str] = mapped_column(String(40), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    epidemiological_week: Mapped[int] = mapped_column(Integer)
    epidemiological_year: Mapped[int] = mapped_column(Integer)
    cases: Mapped[int] = mapped_column(Integer)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incidence_per_100k: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_preliminary: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_score: Mapped[float] = mapped_column(Float, default=1.0)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_runs.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EpidemiologicalBulletinAggregate(Base):
    """Current official BES reference at the resolution actually published by INS.

    These rows are deliberately separate from municipal weekly observations.  BES
    tables mix departments and certified districts and often publish cumulative
    values, so silently feeding them into the municipal training panel would change
    both the geographic unit and the target semantics.
    """

    __tablename__ = "epidemiological_bulletin_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "territory_code",
            "disease",
            "epidemiological_year",
            "epidemiological_week",
            name="uq_bes_source_territory_disease_week",
        ),
        Index("ix_bes_disease_period", "disease", "period_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    territory_code: Mapped[str] = mapped_column(String(8), index=True)
    territory_name: Mapped[str] = mapped_column(String(160))
    territory_level: Mapped[str] = mapped_column(String(30), index=True)
    disease: Mapped[str] = mapped_column(String(40), index=True)
    event_label: Mapped[str] = mapped_column(String(220))
    epidemiological_year: Mapped[int] = mapped_column(Integer, index=True)
    epidemiological_week: Mapped[int] = mapped_column(Integer, index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    cumulative_cases: Mapped[int] = mapped_column(Integer)
    expected_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comparison_basis: Mapped[str] = mapped_column(String(80))
    is_preliminary: Mapped[bool] = mapped_column(Boolean, default=True)
    source_document_url: Mapped[str] = mapped_column(String(1000))
    source_page: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClimateObservation(Base):
    __tablename__ = "climate_observations"
    __table_args__ = (
        UniqueConstraint("municipality_code", "week_start", name="uq_climate_municipality_week"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code", ondelete="CASCADE"), index=True
    )
    week_start: Mapped[date] = mapped_column(Date, index=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_mean_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_relative_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    station_count: Mapped[int] = mapped_column(Integer, default=0)
    interpolation_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, default=1.0)
    metric_provenance: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class VaccinationCoverage(Base):
    __tablename__ = "vaccination_coverages"
    __table_args__ = (
        UniqueConstraint(
            "municipality_code", "year", "month", "vaccine", name="uq_vax_municipality_period"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code", ondelete="CASCADE"), index=True
    )
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer)
    vaccine: Mapped[str] = mapped_column(String(100), index=True)
    source_vaccine_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    period_semantics: Mapped[str] = mapped_column(String(40), default="monthly")
    target_population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doses_applied: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_pct: Mapped[float] = mapped_column(Float)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    raw_record_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DepartmentVaccinationCoverage(Base):
    """PAI covariate at its published resolution; never silently expanded to municipalities."""

    __tablename__ = "department_vaccination_coverages"
    __table_args__ = (
        UniqueConstraint(
            "department_code", "year", "vaccine", name="uq_vax_department_period"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    department_code: Mapped[str] = mapped_column(String(2), index=True)
    department_name: Mapped[str] = mapped_column(String(120))
    territory_level: Mapped[str] = mapped_column(String(20), default="department")
    year: Mapped[int] = mapped_column(Integer, index=True)
    vaccine: Mapped[str] = mapped_column(String(140), index=True)
    source_vaccine_label: Mapped[str] = mapped_column(String(300))
    coverage_pct: Mapped[float] = mapped_column(Float)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"))
    raw_record_sha256: Mapped[str] = mapped_column(String(64))


class DeforestationObservation(Base):
    __tablename__ = "deforestation_observations"
    __table_args__ = (
        UniqueConstraint(
            "municipality_code", "year", "quarter", name="uq_deforestation_municipality_period"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code", ondelete="CASCADE"), index=True
    )
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    deforested_hectares: Mapped[float | None] = mapped_column(Float, nullable=True)
    early_warning_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_active_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class SocioeconomicIndicator(Base):
    __tablename__ = "socioeconomic_indicators"
    __table_args__ = (
        UniqueConstraint("municipality_code", "year", name="uq_socioeconomic_municipality_year"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code", ondelete="CASCADE"), index=True
    )
    year: Mapped[int] = mapped_column(Integer, index=True)
    water_access_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sewer_access_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    overcrowding_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    nbi_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # IRCA municipal (0–100); lower is better water quality. Distinct from CNPV water_access.
    irca_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    urban_population_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rural_population_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    populated_center_population_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    rural_remainder_population_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("disease", "horizon_weeks", "version", name="uq_model_version"),
        Index("ix_model_active", "disease", "horizon_weeks", "stage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    disease: Mapped[str] = mapped_column(String(40), index=True)
    horizon_weeks: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[str] = mapped_column(String(100))
    stage: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    artifact_uri: Mapped[str] = mapped_column(String(1000))
    training_started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    training_ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    feature_names: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    data_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelTrainingRun(Base):
    __tablename__ = "model_training_runs"
    __table_args__ = (Index("ix_training_disease_created", "disease", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    disease: Mapped[str] = mapped_column(String(40), index=True)
    horizons: Mapped[list[int]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    status: Mapped[str] = mapped_column(
        String(30), default=PipelineStatus.PENDING.value, index=True
    )
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint(
            "municipality_code",
            "disease",
            "target_week",
            "horizon_weeks",
            "model_version_id",
            name="uq_forecast_identity",
        ),
        Index("ix_forecast_map", "disease", "horizon_weeks", "issued_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    municipality_code: Mapped[str] = mapped_column(
        ForeignKey("municipalities.code", ondelete="CASCADE"), index=True
    )
    disease: Mapped[str] = mapped_column(String(40), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    target_week: Mapped[date] = mapped_column(Date, index=True)
    horizon_weeks: Mapped[int] = mapped_column(Integer, index=True)
    predicted_cases: Mapped[float] = mapped_column(Float)
    interval_lower: Mapped[float] = mapped_column(Float)
    interval_upper: Mapped[float] = mapped_column(Float)
    outbreak_probability: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20), index=True)
    data_completeness: Mapped[float] = mapped_column(Float, default=1.0)
    observation_cutoff: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    observation_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operationally_eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), index=True
    )
    component_predictions: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict
    )
    drivers: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )
    warnings: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_event_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    forecast_id: Mapped[str] = mapped_column(
        ForeignKey("forecasts.id", ondelete="CASCADE"), unique=True, index=True
    )
    threshold: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
