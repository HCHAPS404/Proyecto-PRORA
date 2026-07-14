"""Add traceable CNPV 2018 urban-rural class composition.

Revision ID: 20260713_0003
Revises: 20260713_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260713_0003"
down_revision: str | None = "20260713_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "socioeconomic_indicators",
        sa.Column("urban_population_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "socioeconomic_indicators",
        sa.Column("rural_population_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "socioeconomic_indicators",
        sa.Column("populated_center_population_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "socioeconomic_indicators",
        sa.Column("rural_remainder_population_pct", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("socioeconomic_indicators", "rural_remainder_population_pct")
    op.drop_column("socioeconomic_indicators", "populated_center_population_pct")
    op.drop_column("socioeconomic_indicators", "rural_population_pct")
    op.drop_column("socioeconomic_indicators", "urban_population_pct")
