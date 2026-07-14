"""Add immutable raw snapshots, quarantine and canonical source-resolution tables.

Revision ID: 20260713_0002
Revises: 9c7f6df28fde
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260713_0002"
down_revision: str | None = "9c7f6df28fde"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vaccination_coverages",
        sa.Column("source_vaccine_label", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "vaccination_coverages",
        sa.Column(
            "period_semantics",
            sa.String(length=40),
            nullable=False,
            server_default="monthly",
        ),
    )
    op.add_column(
        "vaccination_coverages",
        sa.Column("raw_record_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "climate_observations",
        sa.Column("metric_provenance", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "forecasts", sa.Column("observation_cutoff", sa.Date(), nullable=True)
    )
    op.add_column(
        "forecasts", sa.Column("observation_age_days", sa.Integer(), nullable=True)
    )
    op.add_column(
        "forecasts",
        sa.Column(
            "operationally_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f("ix_forecasts_observation_cutoff"), "forecasts", ["observation_cutoff"]
    )
    op.create_index(
        op.f("ix_forecasts_operationally_eligible"),
        "forecasts",
        ["operationally_eligible"],
    )
    op.create_table(
        "raw_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("object_path", sa.String(length=1200), nullable=False),
        sa.Column("manifest_path", sa.String(length=1200), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_raw_snapshots_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_raw_snapshots_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_snapshots")),
    )
    op.create_index(
        op.f("ix_raw_snapshots_ingestion_run_id"),
        "raw_snapshots",
        ["ingestion_run_id"],
        unique=True,
    )
    op.create_index(op.f("ix_raw_snapshots_sha256"), "raw_snapshots", ["sha256"])
    op.create_index(op.f("ix_raw_snapshots_source_id"), "raw_snapshots", ["source_id"])

    op.create_table(
        "quarantine_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_record_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_quarantine_records_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_quarantine_records_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quarantine_records")),
    )
    op.create_index(
        op.f("ix_quarantine_records_ingestion_run_id"),
        "quarantine_records",
        ["ingestion_run_id"],
    )
    op.create_index(
        op.f("ix_quarantine_records_raw_record_sha256"),
        "quarantine_records",
        ["raw_record_sha256"],
    )
    op.create_index(
        op.f("ix_quarantine_records_reason_code"),
        "quarantine_records",
        ["reason_code"],
    )
    op.create_index(
        op.f("ix_quarantine_records_source_id"), "quarantine_records", ["source_id"]
    )
    op.create_index(
        "ix_quarantine_run_reason",
        "quarantine_records",
        ["ingestion_run_id", "reason_code"],
    )

    op.create_table(
        "weather_stations",
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=220), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("technology", sa.String(length=80), nullable=True),
        sa.Column("operational_status", sa.String(length=80), nullable=True),
        sa.Column("department_name", sa.String(length=120), nullable=True),
        sa.Column("municipality_name", sa.String(length=160), nullable=True),
        sa.Column("municipality_code", sa.String(length=5), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=220), nullable=True),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("raw_record_sha256", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_weather_stations_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["municipality_code"],
            ["municipalities.code"],
            name=op.f("fk_weather_stations_municipality_code_municipalities"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_weather_stations_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_weather_stations")),
    )
    op.create_index(
        op.f("ix_weather_stations_municipality_code"),
        "weather_stations",
        ["municipality_code"],
    )
    op.create_index(
        op.f("ix_weather_stations_operational_status"),
        "weather_stations",
        ["operational_status"],
    )
    op.create_index(
        op.f("ix_weather_stations_source_id"), "weather_stations", ["source_id"]
    )

    op.create_table(
        "department_vaccination_coverages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("department_code", sa.String(length=2), nullable=False),
        sa.Column("department_name", sa.String(length=120), nullable=False),
        sa.Column("territory_level", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("vaccine", sa.String(length=140), nullable=False),
        sa.Column("source_vaccine_label", sa.String(length=300), nullable=False),
        sa.Column("coverage_pct", sa.Float(), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("raw_record_sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f(
                "fk_department_vaccination_coverages_ingestion_run_id_ingestion_runs"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_department_vaccination_coverages_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_department_vaccination_coverages")),
        sa.UniqueConstraint(
            "department_code", "year", "vaccine", name="uq_vax_department_period"
        ),
    )
    op.create_index(
        op.f("ix_department_vaccination_coverages_department_code"),
        "department_vaccination_coverages",
        ["department_code"],
    )
    op.create_index(
        op.f("ix_department_vaccination_coverages_source_id"),
        "department_vaccination_coverages",
        ["source_id"],
    )
    op.create_index(
        op.f("ix_department_vaccination_coverages_vaccine"),
        "department_vaccination_coverages",
        ["vaccine"],
    )
    op.create_index(
        op.f("ix_department_vaccination_coverages_year"),
        "department_vaccination_coverages",
        ["year"],
    )


def downgrade() -> None:
    op.drop_table("department_vaccination_coverages")
    op.drop_table("weather_stations")
    op.drop_table("quarantine_records")
    op.drop_table("raw_snapshots")
    op.drop_index(op.f("ix_forecasts_operationally_eligible"), table_name="forecasts")
    op.drop_index(op.f("ix_forecasts_observation_cutoff"), table_name="forecasts")
    op.drop_column("forecasts", "operationally_eligible")
    op.drop_column("forecasts", "observation_age_days")
    op.drop_column("forecasts", "observation_cutoff")
    op.drop_column("climate_observations", "metric_provenance")
    op.drop_column("vaccination_coverages", "raw_record_sha256")
    op.drop_column("vaccination_coverages", "period_semantics")
    op.drop_column("vaccination_coverages", "source_vaccine_label")
