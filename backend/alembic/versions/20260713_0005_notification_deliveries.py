"""Add idempotent and auditable notification deliveries.

Revision ID: 20260713_0005
Revises: 20260713_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260713_0005"
down_revision: str | None = "20260713_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("alert_event_id", sa.String(length=36), nullable=False),
        sa.Column("alert_rule_id", sa.String(length=36), nullable=True),
        sa.Column("rule_name", sa.String(length=140), nullable=False),
        sa.Column("disease", sa.String(length=80), nullable=False),
        sa.Column("municipality_code", sa.String(length=5), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("failure_reason", sa.String(length=300), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_event_id"],
            ["alert_events.id"],
            name=op.f("fk_notification_deliveries_alert_event_id_alert_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["alert_rule_id"],
            ["alert_rules.id"],
            name=op.f("fk_notification_deliveries_alert_rule_id_alert_rules"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_deliveries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint(
            "deduplication_key", name="uq_notification_delivery_dedup"
        ),
    )
    op.create_index(
        op.f("ix_notification_deliveries_alert_event_id"),
        "notification_deliveries",
        ["alert_event_id"],
    )
    op.create_index(
        op.f("ix_notification_deliveries_alert_rule_id"),
        "notification_deliveries",
        ["alert_rule_id"],
    )
    op.create_index(
        op.f("ix_notification_deliveries_channel"),
        "notification_deliveries",
        ["channel"],
    )
    op.create_index(
        op.f("ix_notification_deliveries_disease"),
        "notification_deliveries",
        ["disease"],
    )
    op.create_index(
        op.f("ix_notification_deliveries_municipality_code"),
        "notification_deliveries",
        ["municipality_code"],
    )
    op.create_index(
        op.f("ix_notification_deliveries_status"),
        "notification_deliveries",
        ["status"],
    )
    op.create_index(
        op.f("ix_notification_deliveries_user_id"),
        "notification_deliveries",
        ["user_id"],
    )
    op.create_index(
        "ix_notification_user_created",
        "notification_deliveries",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_notification_user_unread",
        "notification_deliveries",
        ["user_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
