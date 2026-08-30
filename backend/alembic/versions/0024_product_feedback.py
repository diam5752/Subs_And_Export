"""Add the durable product-feedback inbox and email outbox.

Revision ID: 0024_product_feedback
Revises: 0023_beta_login_promotion
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_product_feedback"
down_revision = "0023_beta_login_promotion"
branch_labels = None
depends_on = None

DOWNGRADE_WITH_FEEDBACK_ERROR = "Cannot downgrade product feedback after messages were submitted."


def upgrade() -> None:
    """Create a privacy-bounded inbox with a durable notification queue."""
    op.create_table(
        "product_feedback",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("page_title", sa.String(length=255), nullable=False),
        sa.Column("submitter_user_id", sa.String(length=64), nullable=True),
        sa.Column("submitter_key_hash", sa.String(length=64), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("dedupe_day", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column(
            "notification_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "notification_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("notification_next_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("notification_sent_at", sa.BigInteger(), nullable=True),
        sa.Column("notification_last_error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "category IN ('idea','bug','complaint','chat')",
            name="chk_product_feedback_category",
        ),
        sa.CheckConstraint(
            "status IN ('new','reviewed','closed')",
            name="chk_product_feedback_status",
        ),
        sa.CheckConstraint(
            "char_length(message) BETWEEN 10 AND 2000",
            name="chk_product_feedback_message_length",
        ),
        sa.CheckConstraint(
            "notification_status IN ('pending','sending','sent')",
            name="chk_product_feedback_notification_status",
        ),
        sa.CheckConstraint(
            "notification_attempts >= 0",
            name="chk_product_feedback_notification_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["submitter_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submitter_key_hash",
            "message_hash",
            "dedupe_day",
            name="uq_product_feedback_daily_duplicate",
        ),
    )
    op.create_index(
        "ix_product_feedback_submitter_user_id",
        "product_feedback",
        ["submitter_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_feedback_status_created",
        "product_feedback",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_product_feedback_notification_queue",
        "product_feedback",
        ["notification_status", "notification_next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop only an empty inbox; submitted user messages are rollback evidence."""
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE product_feedback IN ACCESS EXCLUSIVE MODE"))
    row_count = int(
        connection.execute(sa.text("SELECT COUNT(*) FROM product_feedback")).scalar_one(),
    )
    if row_count:
        raise RuntimeError(DOWNGRADE_WITH_FEEDBACK_ERROR)

    op.drop_index(
        "ix_product_feedback_notification_queue",
        table_name="product_feedback",
    )
    op.drop_index(
        "ix_product_feedback_status_created",
        table_name="product_feedback",
    )
    op.drop_index(
        "ix_product_feedback_submitter_user_id",
        table_name="product_feedback",
    )
    op.drop_table("product_feedback")
