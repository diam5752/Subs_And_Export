"""Reconcile cached user_points balances.

Revision ID: 0003_reconcile_points_balances
Revises: 0002_points_tables
Create Date: 2025-12-18
"""

from __future__ import annotations

import time

import sqlalchemy as sa
from alembic import op

revision = "0003_reconcile_points_balances"
down_revision = "0002_points_tables"
branch_labels = None
depends_on = None

STARTING_POINTS_BALANCE = 1000


def upgrade() -> None:
    now = int(time.time())

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE user_points
            SET balance = (
                SELECT CASE
                    WHEN COALESCE(MAX(CASE WHEN reason = 'initial_balance' THEN 1 ELSE 0 END), 0) = 1
                        THEN COALESCE(SUM(delta), 0)
                    ELSE :starting_balance + COALESCE(SUM(delta), 0)
                END
                FROM point_transactions
                WHERE point_transactions.user_id = user_points.user_id
            ),
            updated_at = :now
            """
        ),
        {"starting_balance": STARTING_POINTS_BALANCE, "now": now},
    )


def downgrade() -> None:
    # Data-only migration; no safe downgrade.
    pass
