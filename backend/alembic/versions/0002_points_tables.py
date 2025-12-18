"""Add points tables.

Revision ID: 0002_points_tables
Revises: 0001_initial_schema
Create Date: 2025-12-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_points_tables"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_value = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "user_points",
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("balance >= 0", name="chk_user_points_balance_nonnegative"),
    )

    op.create_table(
        "point_transactions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("meta", json_value, nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("delta != 0", name="chk_point_transactions_delta_nonzero"),
    )
    op.create_index("ix_point_transactions_user_id", "point_transactions", ["user_id"])
    op.create_index(
        "idx_point_transactions_user_created_at",
        "point_transactions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_point_transactions_user_created_at", table_name="point_transactions")
    op.drop_index("ix_point_transactions_user_id", table_name="point_transactions")
    op.drop_table("point_transactions")
    op.drop_table("user_points")

