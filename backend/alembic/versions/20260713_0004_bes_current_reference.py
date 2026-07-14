"""Add official BES current-reference aggregates.

Revision ID: 20260713_0004
Revises: 20260713_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260713_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_name = "epidemiological_bulletin_aggregates"
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Development historically allowed SQLAlchemy ``create_all`` on startup.
    # A database opened once by that build can therefore already contain the
    # exact ORM table while its Alembic revision is still at 0003.  Treat that
    # state as a recoverable bootstrap, then create any indexes that are absent.
    if table_name not in inspector.get_table_names():
        op.create_table(
            table_name,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("territory_code", sa.String(length=8), nullable=False),
            sa.Column("territory_name", sa.String(length=160), nullable=False),
            sa.Column("territory_level", sa.String(length=30), nullable=False),
            sa.Column("disease", sa.String(length=40), nullable=False),
            sa.Column("event_label", sa.String(length=220), nullable=False),
            sa.Column("epidemiological_year", sa.Integer(), nullable=False),
            sa.Column("epidemiological_week", sa.Integer(), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("cumulative_cases", sa.Integer(), nullable=False),
            sa.Column("expected_cases", sa.Integer(), nullable=True),
            sa.Column("observed_cases", sa.Integer(), nullable=True),
            sa.Column("comparison_basis", sa.String(length=80), nullable=False),
            sa.Column("is_preliminary", sa.Boolean(), nullable=False),
            sa.Column("source_document_url", sa.String(length=1000), nullable=False),
            sa.Column("source_page", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.String(length=80), nullable=False),
            sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"]),
            sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "source_id",
                "territory_code",
                "disease",
                "epidemiological_year",
                "epidemiological_week",
                name="uq_bes_source_territory_disease_week",
            ),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes(table_name)}
    indexes = (
        ("ix_bes_disease_period", ["disease", "period_end"]),
        (op.f("ix_epidemiological_bulletin_aggregates_territory_code"), ["territory_code"]),
        (op.f("ix_epidemiological_bulletin_aggregates_territory_level"), ["territory_level"]),
        (op.f("ix_epidemiological_bulletin_aggregates_disease"), ["disease"]),
        (op.f("ix_epidemiological_bulletin_aggregates_epidemiological_year"), ["epidemiological_year"]),
        (op.f("ix_epidemiological_bulletin_aggregates_epidemiological_week"), ["epidemiological_week"]),
        (op.f("ix_epidemiological_bulletin_aggregates_period_end"), ["period_end"]),
        (op.f("ix_epidemiological_bulletin_aggregates_source_id"), ["source_id"]),
        (op.f("ix_epidemiological_bulletin_aggregates_ingestion_run_id"), ["ingestion_run_id"]),
    )
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, table_name, columns)


def downgrade() -> None:
    op.drop_table("epidemiological_bulletin_aggregates")
