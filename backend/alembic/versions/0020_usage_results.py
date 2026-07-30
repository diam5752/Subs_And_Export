"""Add temporary usage-result replay storage.

Revision ID: 0020_usage_results
Revises: 0019_zero_wallet_default
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_usage_results"
down_revision = "0019_zero_wallet_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create one replayable provider result per usage-ledger entry."""
    json_value = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "usage_results",
        sa.Column("ledger_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("payload", json_value, nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_id"],
            ["usage_ledger.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ledger_id"),
    )
    op.create_index(
        "ix_usage_results_job_id",
        "usage_results",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove temporary replay-result storage."""
    op.drop_index("ix_usage_results_job_id", table_name="usage_results")
    op.drop_table("usage_results")
