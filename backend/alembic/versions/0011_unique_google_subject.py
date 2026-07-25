"""Make each Google subject usable by only one GSUBS account.

Revision ID: 0011_unique_google_subject
Revises: 0010_unique_payment_intent
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op

revision = "0011_unique_google_subject"
down_revision = "0010_unique_payment_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.exec_driver_sql(
        """
        SELECT google_sub
        FROM users
        WHERE google_sub IS NOT NULL
        GROUP BY google_sub
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).scalar_one_or_none()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce unique Google subjects while duplicate identities exist."
        )
    op.drop_index("ix_users_google_sub", table_name="users")
    op.create_index(
        "ix_users_google_sub",
        "users",
        ["google_sub"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_google_sub", table_name="users")
    op.create_index(
        "ix_users_google_sub",
        "users",
        ["google_sub"],
        unique=False,
    )
