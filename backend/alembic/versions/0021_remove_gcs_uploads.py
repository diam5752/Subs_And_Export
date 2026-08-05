"""Remove the retired Google Cloud Storage upload-session table.

Revision ID: 0021_remove_gcs_uploads
Revises: 0020_usage_results
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op

revision = "0021_remove_gcs_uploads"
down_revision = "0020_usage_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop upload sessions now that all media is stored locally."""
    op.drop_table("gcs_uploads", if_exists=True)


def downgrade() -> None:
    """Keep the retired cloud-upload schema removed on historical downgrades."""
    # Recreating the table would reintroduce dead cloud-storage state. This
    # revision is intentionally a schema no-op in the reverse direction so
    # later, unrelated migrations can still be inspected or downgraded.
