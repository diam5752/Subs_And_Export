"""Remove the retired Google Cloud Storage upload-session table.

Revision ID: 0021_remove_gcs_uploads
Revises: 0020_usage_results
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_remove_gcs_uploads"
down_revision = "0020_usage_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop only an empty legacy upload schema.

    A non-empty upload row or persisted job reference is deletion evidence,
    not disposable session state.  Keep the schema intact and stop the release
    until the retired provider objects have been inventoried and removed.
    """
    connection = op.get_bind()
    legacy_table_exists = bool(
        connection.execute(
            sa.text("SELECT to_regclass('public.gcs_uploads') IS NOT NULL"),
        ).scalar_one(),
    )
    upload_rows = (
        int(
            connection.execute(sa.text("SELECT count(*) FROM gcs_uploads")).scalar_one(),
        )
        if legacy_table_exists
        else 0
    )
    job_references = int(
        connection.execute(
            sa.text(
                """
                SELECT count(*)
                FROM jobs
                WHERE result_data ? 'source_gcs_object'
                """,
            ),
        ).scalar_one(),
    )
    if upload_rows or job_references:
        raise RuntimeError(
            "Refusing to remove retired cloud-storage evidence: legacy GCS object references remain",
        )

    op.drop_table("gcs_uploads", if_exists=True)


def downgrade() -> None:
    """Keep the retired cloud-upload schema removed on historical downgrades."""
    # Recreating the table would reintroduce dead cloud-storage state. This
    # revision is intentionally a schema no-op in the reverse direction so
    # later, unrelated migrations can still be inspected or downgraded.
