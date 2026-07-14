"""Add socioeconomic irca_index column.

Revision ID: 20260714_0006
Revises: 20260713_0005
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260714_0006"
down_revision = "20260713_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "socioeconomic_indicators",
        sa.Column("irca_index", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("socioeconomic_indicators", "irca_index")
