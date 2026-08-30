"""Restore the reviewed Beta login campaign cap to 20 claims.

Revision ID: 0027_restore_beta_promo_cap
Revises: 0026_retire_text_models
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "0027_restore_beta_promo_cap"
down_revision = "0026_retire_text_models"
branch_labels = None
depends_on = None

BETA_CAMPAIGN_ID = "beta_first_20_logins_v1"
PREVIOUS_MAX_CLAIMS = 50
RESTORED_MAX_CLAIMS = 20
CREDIT_AMOUNT = 30
CAMPAIGN_CONTRACT_ERROR = "The Beta login promotion does not match the reviewed 50-by-30 predecessor contract."
UNSAFE_RESTORE_ERROR = "Cannot restore the 20-slot Beta promotion after a slot above 20 was awarded."


def _lock_and_read_campaign(connection: Connection) -> tuple[int, int, int]:
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
    if campaign is None:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)
    return (
        int(campaign.max_claims),
        int(campaign.credit_amount),
        int(campaign.claimed_count),
    )


def upgrade() -> None:
    """Reduce the existing campaign only while every awarded slot still fits."""
    connection = op.get_bind()
    max_claims, credit_amount, claimed_count = _lock_and_read_campaign(connection)
    if max_claims != PREVIOUS_MAX_CLAIMS or credit_amount != CREDIT_AMOUNT:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)

    expanded_claims = int(
        connection.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM credit_promotion_claims
                WHERE campaign_id = :campaign_id
                  AND slot_number > :restored_max_claims
                """
            ),
            {
                "campaign_id": BETA_CAMPAIGN_ID,
                "restored_max_claims": RESTORED_MAX_CLAIMS,
            },
        ).scalar_one()
    )
    if claimed_count > RESTORED_MAX_CLAIMS or expanded_claims:
        raise RuntimeError(UNSAFE_RESTORE_ERROR)

    result = connection.execute(
        sa.text(
            """
            UPDATE credit_promotion_campaigns
            SET max_claims = :restored_max_claims
            WHERE id = :campaign_id
              AND max_claims = :previous_max_claims
              AND credit_amount = :credit_amount
              AND claimed_count <= :restored_max_claims
            """
        ),
        {
            "campaign_id": BETA_CAMPAIGN_ID,
            "previous_max_claims": PREVIOUS_MAX_CLAIMS,
            "restored_max_claims": RESTORED_MAX_CLAIMS,
            "credit_amount": CREDIT_AMOUNT,
        },
    )
    if result.rowcount != 1:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)


def downgrade() -> None:
    """Return to the predecessor cap without changing claims or ordinals."""
    connection = op.get_bind()
    max_claims, credit_amount, claimed_count = _lock_and_read_campaign(connection)
    if max_claims != RESTORED_MAX_CLAIMS or credit_amount != CREDIT_AMOUNT or claimed_count > RESTORED_MAX_CLAIMS:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)

    result = connection.execute(
        sa.text(
            """
            UPDATE credit_promotion_campaigns
            SET max_claims = :previous_max_claims
            WHERE id = :campaign_id
              AND max_claims = :restored_max_claims
              AND credit_amount = :credit_amount
              AND claimed_count <= :restored_max_claims
            """
        ),
        {
            "campaign_id": BETA_CAMPAIGN_ID,
            "previous_max_claims": PREVIOUS_MAX_CLAIMS,
            "restored_max_claims": RESTORED_MAX_CLAIMS,
            "credit_amount": CREDIT_AMOUNT,
        },
    )
    if result.rowcount != 1:
        raise RuntimeError(CAMPAIGN_CONTRACT_ERROR)
