"""Store the verified Google profile picture URL.

Revision ID: 0012_google_avatar_url
Revises: 0011_unique_google_subject
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_google_avatar_url"
down_revision = "0011_unique_google_subject"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
