"""add_usage_ledger_table

Revision ID: 0004_usage_ledger
Revises: 429a30578e50
Create Date: 2025-12-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_usage_ledger"
down_revision = "429a30578e50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_value = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=True),
        sa.Column("units", json_value, nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("credits_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_usage_ledger_user_created", "usage_ledger", ["user_id", "created_at"], unique=False)
    op.create_index("idx_usage_ledger_action", "usage_ledger", ["action"], unique=False)
    op.create_index("idx_usage_ledger_status", "usage_ledger", ["status"], unique=False)
    op.create_index("ix_usage_ledger_idempotency_key", "usage_ledger", ["idempotency_key"], unique=True)
    op.create_index("ix_usage_ledger_job_id", "usage_ledger", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_usage_ledger_job_id", table_name="usage_ledger")
    op.drop_index("ix_usage_ledger_idempotency_key", table_name="usage_ledger")
    op.drop_index("idx_usage_ledger_status", table_name="usage_ledger")
    op.drop_index("idx_usage_ledger_action", table_name="usage_ledger")
    op.drop_index("idx_usage_ledger_user_created", table_name="usage_ledger")
    op.drop_table("usage_ledger")
