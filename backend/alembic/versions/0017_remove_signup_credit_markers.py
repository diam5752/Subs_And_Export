"""Remove obsolete deleted-email markers for signup credits.

Revision ID: 0017_remove_signup_markers
Revises: 0016_manual_refund_accounting
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_remove_signup_markers"
down_revision = "0016_manual_refund_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("deleted_emails")


def downgrade() -> None:
    op.create_table(
        "deleted_emails",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("deleted_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("email_hash"),
    )
