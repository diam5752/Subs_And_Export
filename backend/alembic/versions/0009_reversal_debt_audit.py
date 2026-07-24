"""Audit reversal-debt-only wallet mutations.

Revision ID: 0009_reversal_debt_audit
Revises: 0008_video_credits_and_billing
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_reversal_debt_audit"
down_revision = "0008_video_credits_and_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "point_transactions",
        sa.Column(
            "reversal_debt_delta",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.drop_constraint(
        "chk_point_transactions_delta_nonzero",
        "point_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "chk_point_transactions_effect_nonzero",
        "point_transactions",
        "delta != 0 OR reversal_debt_delta != 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_point_transactions_effect_nonzero",
        "point_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "chk_point_transactions_delta_nonzero",
        "point_transactions",
        "delta != 0",
    )
    op.drop_column("point_transactions", "reversal_debt_delta")
