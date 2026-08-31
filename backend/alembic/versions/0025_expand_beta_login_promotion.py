"""Expand the existing Beta login campaign from 20 to 50 claims.

Revision ID: 0025_expand_beta_login_promotion
Revises: 0024_product_feedback
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_expand_beta_login_promotion"
down_revision = "0024_product_feedback"
branch_labels = None
depends_on = None

BETA_CAMPAIGN_ID = "beta_first_20_logins_v1"
ORIGINAL_MAX_CLAIMS = 20
EXPANDED_MAX_CLAIMS = 50
CREDIT_AMOUNT = 30
CAMPAIGN_CONTRACT_ERROR = "The Beta login promotion does not match the reviewed 20-by-30 contract."
UNSAFE_DOWNGRADE_ERROR = "Cannot reduce the Beta login promotion after more than 20 campaign slots were awarded."


def upgrade() -> None:
    """Increase the cap without replacing campaign or recipient identity."""
    connection = op.get_bind()
    result = connection.execute(
        sa.text(
            """
            UPDATE credit_promotion_campaigns
            SET max_claims = :expanded_max_claims
            WHERE id = :campaign_id
              AND max_claims = :original_max_claims
              AND credit_amount = :credit_amount
              AND claimed_count BETWEEN 0 AND :original_max_claims
            """
        ),
        {
            "campaign_id": BETA_CAMPAIGN_ID,
            "original_max_claims": ORIGINAL_MAX_CLAIMS,
            "expanded_max_claims": EXPANDED_MAX_CLAIMS,
            "credit_amount": CREDIT_AMOUNT,
        },
    )
    if result.rowcount != 1:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)


def downgrade() -> None:
    """Restore the old cap only while no expanded slot has been awarded."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            LOCK TABLE credit_promotion_campaigns, credit_promotion_claims
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    campaign = connection.execute(
        sa.text(
            """
            SELECT max_claims, credit_amount, claimed_count
            FROM credit_promotion_campaigns
            WHERE id = :campaign_id
            FOR UPDATE
            """
        ),
        {"campaign_id": BETA_CAMPAIGN_ID},
    ).one_or_none()
    if (
        campaign is None
        or int(campaign.max_claims) != EXPANDED_MAX_CLAIMS
        or int(campaign.credit_amount) != CREDIT_AMOUNT
    ):
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)

    expanded_claims = int(
        connection.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM credit_promotion_claims
                WHERE campaign_id = :campaign_id
                  AND slot_number > :original_max_claims
                """
            ),
            {
                "campaign_id": BETA_CAMPAIGN_ID,
                "original_max_claims": ORIGINAL_MAX_CLAIMS,
            },
        ).scalar_one()
    )
    if int(campaign.claimed_count) > ORIGINAL_MAX_CLAIMS or expanded_claims:
        raise RuntimeError(UNSAFE_DOWNGRADE_ERROR)

    result = connection.execute(
        sa.text(
            """
            UPDATE credit_promotion_campaigns
            SET max_claims = :original_max_claims
            WHERE id = :campaign_id
              AND max_claims = :expanded_max_claims
              AND credit_amount = :credit_amount
              AND claimed_count <= :original_max_claims
            """
        ),
        {
            "campaign_id": BETA_CAMPAIGN_ID,
            "original_max_claims": ORIGINAL_MAX_CLAIMS,
            "expanded_max_claims": EXPANDED_MAX_CLAIMS,
            "credit_amount": CREDIT_AMOUNT,
        },
    )
    if result.rowcount != 1:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)
