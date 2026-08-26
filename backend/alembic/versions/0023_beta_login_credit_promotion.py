"""Add the bounded Beta login credit campaign.

Revision ID: 0023_beta_login_promotion
Revises: 0022_cancelling_job_status
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_beta_login_promotion"
down_revision = "0022_cancelling_job_status"
branch_labels = None
depends_on = None

BETA_CAMPAIGN_ID = "beta_first_20_logins_v1"
DOWNGRADE_WITH_AWARDS_ERROR = (
    "Cannot downgrade the Beta login promotion after any campaign slot was awarded."
)


def upgrade() -> None:
    """Create one locked campaign counter and its auditable user claims."""
    op.create_table(
        "credit_promotion_campaigns",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("credit_amount", sa.Integer(), nullable=False),
        sa.Column("claimed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "max_claims > 0",
            name="chk_credit_promotion_campaigns_max_claims_positive",
        ),
        sa.CheckConstraint(
            "credit_amount > 0",
            name="chk_credit_promotion_campaigns_credit_amount_positive",
        ),
        sa.CheckConstraint(
            "claimed_count >= 0 AND claimed_count <= max_claims",
            name="chk_credit_promotion_campaigns_claimed_count",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "credit_promotion_claims",
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("credit_amount", sa.Integer(), nullable=False),
        sa.Column("point_transaction_id", sa.String(length=32), nullable=False),
        sa.Column("claimed_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "slot_number > 0",
            name="chk_credit_promotion_claims_slot_positive",
        ),
        sa.CheckConstraint(
            "credit_amount > 0",
            name="chk_credit_promotion_claims_credit_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["credit_promotion_campaigns.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["point_transaction_id"],
            ["point_transactions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("campaign_id", "user_id"),
        sa.UniqueConstraint(
            "campaign_id",
            "slot_number",
            name="uq_credit_promotion_claims_campaign_slot",
        ),
        sa.UniqueConstraint(
            "point_transaction_id",
            name="uq_credit_promotion_claims_point_transaction",
        ),
    )
    op.create_index(
        "ix_credit_promotion_claims_user_id",
        "credit_promotion_claims",
        ["user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO credit_promotion_campaigns (
                id,
                max_claims,
                credit_amount,
                claimed_count,
                created_at
            ) VALUES (
                :campaign_id,
                20,
                30,
                0,
                EXTRACT(EPOCH FROM clock_timestamp())::INTEGER
            )
            """
        ).bindparams(campaign_id=BETA_CAMPAIGN_ID)
    )


def downgrade() -> None:
    """Remove only an unused campaign; awarded slots are rollback evidence."""
    connection = op.get_bind()
    # Serialize against the same campaign table every login claimant locks.
    # This prevents a grant from landing between the evidence check and DDL.
    connection.execute(
        sa.text(
            """
            LOCK TABLE credit_promotion_campaigns, credit_promotion_claims
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    awarded_slots = int(
        connection.execute(
            sa.text(
                """
                SELECT COALESCE(SUM(claimed_count), 0)
                FROM credit_promotion_campaigns
                """
            )
        ).scalar_one()
    )
    claim_rows = int(
        connection.execute(
            sa.text("SELECT COUNT(*) FROM credit_promotion_claims")
        ).scalar_one()
    )
    ledger_rows = int(
        connection.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM point_transactions
                WHERE reason = 'beta_login_credit'
                """
            )
        ).scalar_one()
    )
    if awarded_slots or claim_rows or ledger_rows:
        raise RuntimeError(DOWNGRADE_WITH_AWARDS_ERROR)

    op.drop_index(
        "ix_credit_promotion_claims_user_id",
        table_name="credit_promotion_claims",
    )
    op.drop_table("credit_promotion_claims")
    op.drop_table("credit_promotion_campaigns")
