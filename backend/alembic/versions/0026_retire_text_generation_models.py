"""Retire the unused text-generation model catalog.

Revision ID: 0026_retire_text_models
Revises: 0025_expand_beta_login_promotion
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_retire_text_models"
down_revision = "0025_expand_beta_login_promotion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove unused catalog rows while preserving referenced audit history."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE ai_models
            SET active = FALSE
            WHERE id LIKE 'gpt-%'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM ai_models AS model
            WHERE model.id LIKE 'gpt-%'
              AND NOT EXISTS (
                  SELECT 1
                  FROM token_usage AS usage
                  WHERE usage.model_id = model.id
              )
            """
        )
    )


def downgrade() -> None:
    """Do not recreate retired provider configuration during rollback."""
