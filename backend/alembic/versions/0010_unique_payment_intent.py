"""Make one Stripe PaymentIntent usable by only one credit purchase.

Revision ID: 0010_unique_payment_intent
Revises: 0009_reversal_debt_audit
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "0010_unique_payment_intent"
down_revision = "0009_reversal_debt_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_credit_purchases_payment_intent",
        table_name="credit_purchases",
    )
    op.create_unique_constraint(
        "uq_credit_purchases_payment_intent",
        "credit_purchases",
        ["payment_intent_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_credit_purchases_payment_intent",
        "credit_purchases",
        type_="unique",
    )
    op.create_index(
        "ix_credit_purchases_payment_intent",
        "credit_purchases",
        ["payment_intent_id"],
    )
