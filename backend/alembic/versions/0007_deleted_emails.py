"""Add deleted emails table.

Revision ID: 0007_deleted_emails
Revises: 0006_email_verified
Create Date: 2025-12-21

"""

from alembic import op
import sqlalchemy as sa


revision = "0007_deleted_emails"
down_revision = "0006_email_verified"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deleted_emails",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("deleted_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("email_hash"),
    )


def downgrade() -> None:
    op.drop_table("deleted_emails")
