"""Make the database-side wallet default zero.

Revision ID: 0019_zero_wallet_default
Revises: 0018_approved_contract_delivery
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op

revision = "0019_zero_wallet_default"
down_revision = "0018_approved_contract_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Prevent raw or compatibility inserts from granting signup credits."""
    op.alter_column(
        "user_points",
        "balance",
        server_default="0",
    )


def downgrade() -> None:
    """Keep the zero default; rollback must not resurrect signup credits."""
    op.alter_column(
        "user_points",
        "balance",
        server_default="0",
    )
