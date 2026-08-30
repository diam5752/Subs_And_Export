"""Allow approved account-vault contract-confirmation delivery.

Revision ID: 0018_approved_contract_delivery
Revises: 0017_remove_signup_markers
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_approved_contract_delivery"
down_revision = "0017_remove_signup_markers"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "chk_billing_contract_confirmations_delivery"
_APPROVED_STATUS = "available_approved"
_PENDING_STATUS = "available_pending_external_approval"


def upgrade() -> None:
    """Preserve legacy evidence while allowing reviewed delivery evidence."""
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "billing_contract_confirmations",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "billing_contract_confirmations",
        (f"delivery_channel = 'account_vault' AND delivery_status IN ('{_PENDING_STATUS}', '{_APPROVED_STATUS}')"),
    )


def downgrade() -> None:
    """Refuse to discard support while approved evidence still exists."""
    bind = op.get_bind()
    # Match the established billing writer/downgrade lock order so a
    # concurrent confirmation cannot deadlock or appear after the safety scan.
    bind.execute(
        sa.text(
            """
            LOCK TABLE
                public.billing_withdrawal_requests,
                public.billing_contract_confirmations,
                public.billing_withdrawal_resolutions,
                public.billing_adjustment_records
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    incompatible_evidence_exists = bool(
        bind.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM public.billing_contract_confirmations
                    WHERE delivery_channel IS DISTINCT FROM 'account_vault'
                       OR delivery_status IS DISTINCT FROM :pending_status
                )
                """
            ),
            {"pending_status": _PENDING_STATUS},
        ).scalar_one()
    )
    if incompatible_evidence_exists:
        raise RuntimeError(
            "Cannot downgrade approved contract-confirmation delivery while approved durable evidence exists."
        )
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "billing_contract_confirmations",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "billing_contract_confirmations",
        (f"delivery_channel = 'account_vault' AND delivery_status = '{_PENDING_STATUS}'"),
    )
