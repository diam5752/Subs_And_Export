"""Add a non-terminal cancelling job status.

Revision ID: 0022_cancelling_job_status
Revises: 0021_remove_gcs_uploads
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_cancelling_job_status"
down_revision = "0021_remove_gcs_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep cancellation non-terminal until the worker has stopped and cleaned."""
    op.drop_constraint("chk_jobs_status", "jobs", type_="check")
    op.create_check_constraint(
        "chk_jobs_status",
        "jobs",
        "status IN ('pending','processing','cancelling','completed','failed','cancelled')",
    )


def downgrade() -> None:
    """Refuse to turn an unfinished cleanup into an older terminal state."""
    cancelling_jobs = int(
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM jobs WHERE status = 'cancelling'"),
        )
        .scalar_one(),
    )
    if cancelling_jobs:
        raise RuntimeError(
            "Refusing schema downgrade while job cancellation cleanup is unfinished",
        )
    op.drop_constraint("chk_jobs_status", "jobs", type_="check")
    op.create_check_constraint(
        "chk_jobs_status",
        "jobs",
        "status IN ('pending','processing','completed','failed','cancelled')",
    )
