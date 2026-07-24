"""Add paid-credit, Stripe purchase, webhook, and provider-budget state.

Revision ID: 0008_video_credits_and_billing
Revises: 0007_deleted_emails
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_video_credits_and_billing"
down_revision = "0007_deleted_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_value = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.add_column(
        "user_points",
        sa.Column("paid_balance", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_points",
        sa.Column("reversal_debt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "chk_user_points_paid_balance_nonnegative",
        "user_points",
        "paid_balance >= 0",
    )
    op.create_check_constraint(
        "chk_user_points_paid_balance_within_total",
        "user_points",
        "paid_balance <= balance",
    )
    op.create_check_constraint(
        "chk_user_points_reversal_debt_nonnegative",
        "user_points",
        "reversal_debt >= 0",
    )

    op.add_column(
        "point_transactions",
        sa.Column("paid_delta", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "usage_ledger",
        sa.Column("paid_credits_reserved", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "credit_purchases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="stripe"),
        sa.Column("package_key", sa.String(length=32), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("amount_eur_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="eur"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("integration_identifier", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fulfilled_at", sa.Integer(), nullable=True),
        sa.Column("refunded_amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dispute_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reversed_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reversal_debt_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot", json_value, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("credits > 0", name="chk_credit_purchases_credits_positive"),
        sa.CheckConstraint("amount_eur_cents > 0", name="chk_credit_purchases_amount_positive"),
        sa.CheckConstraint("refunded_amount_cents >= 0", name="chk_credit_purchases_refund_nonnegative"),
        sa.CheckConstraint(
            "reversed_credits >= 0 AND reversed_credits <= credits",
            name="chk_credit_purchases_reversed_credits",
        ),
        sa.CheckConstraint(
            "reversal_debt_credits >= 0 AND reversal_debt_credits <= reversed_credits",
            name="chk_credit_purchases_reversal_debt",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_purchases_idempotency_key"),
        sa.UniqueConstraint("checkout_session_id", name="uq_credit_purchases_checkout_session"),
    )
    op.create_index("ix_credit_purchases_user_created", "credit_purchases", ["user_id", "created_at"])
    op.create_index("ix_credit_purchases_payment_intent", "credit_purchases", ["payment_intent_id"])
    op.create_index("ix_credit_purchases_status", "credit_purchases", ["status"])

    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stripe_webhook_events_status_created",
        "stripe_webhook_events",
        ["status", "created_at"],
    )

    op.create_table(
        "provider_budget_windows",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("period_start", sa.Integer(), nullable=False),
        sa.Column("reserved_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("scope IN ('day','month')", name="chk_provider_budget_windows_scope"),
        sa.CheckConstraint("reserved_usd >= 0", name="chk_provider_budget_windows_reserved"),
        sa.CheckConstraint("spent_usd >= 0", name="chk_provider_budget_windows_spent"),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "provider_budget_reservations",
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "daily_window_key",
            sa.String(length=64),
            sa.ForeignKey("provider_budget_windows.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "monthly_window_key",
            sa.String(length=64),
            sa.ForeignKey("provider_budget_windows.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("estimated_usd", sa.Float(), nullable=False),
        sa.Column("actual_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("estimated_usd >= 0", name="chk_provider_budget_reservation_estimate"),
        sa.CheckConstraint("actual_usd >= 0", name="chk_provider_budget_reservation_actual"),
        sa.CheckConstraint(
            "status IN ('reserved','finalized','released')",
            name="chk_provider_budget_reservation_status",
        ),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_provider_budget_reservations_status",
        "provider_budget_reservations",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_budget_reservations_status", table_name="provider_budget_reservations")
    op.drop_table("provider_budget_reservations")
    op.drop_table("provider_budget_windows")
    op.drop_index("ix_stripe_webhook_events_status_created", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")
    op.drop_index("ix_credit_purchases_status", table_name="credit_purchases")
    op.drop_index("ix_credit_purchases_payment_intent", table_name="credit_purchases")
    op.drop_index("ix_credit_purchases_user_created", table_name="credit_purchases")
    op.drop_table("credit_purchases")
    op.drop_column("usage_ledger", "paid_credits_reserved")
    op.drop_column("point_transactions", "paid_delta")
    op.drop_constraint("chk_user_points_reversal_debt_nonnegative", "user_points", type_="check")
    op.drop_constraint("chk_user_points_paid_balance_within_total", "user_points", type_="check")
    op.drop_constraint("chk_user_points_paid_balance_nonnegative", "user_points", type_="check")
    op.drop_column("user_points", "reversal_debt")
    op.drop_column("user_points", "paid_balance")
