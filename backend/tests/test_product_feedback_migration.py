"""Direct migration safety contract for the durable feedback inbox."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *arguments],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env={**os.environ, "GSP_DATABASE_URL": database_url},
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )


@contextmanager
def _isolated_database() -> Iterator[tuple[str, str]]:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        ),
    )
    database_name = f"gsp_feedback_{uuid.uuid4().hex[:12]}"
    admin_url = configured_url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False,
    )
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("Database role cannot create the isolated migration database")

    database_url = configured_url.set(database=database_name).render_as_string(hide_password=False)
    connection_url = configured_url.set(
        drivername="postgresql",
        database=database_name,
    ).render_as_string(hide_password=False)
    try:
        yield database_url, connection_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def test_feedback_migration_preserves_submitted_messages_on_downgrade() -> None:
    with _isolated_database() as (database_url, connection_url):
        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version",
            ).fetchone() == ("0026_retire_text_models",)

        clean_downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0023_beta_login_promotion",
        )
        assert clean_downgrade.returncode == 0, clean_downgrade.stderr

        assert _run_alembic(database_url, "upgrade", "head").returncode == 0
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute(
                """
                INSERT INTO product_feedback (
                    id, category, status, message, source_path, page_title,
                    submitter_user_id, submitter_key_hash, message_hash,
                    dedupe_day, created_at, notification_status,
                    notification_attempts, notification_next_attempt_at
                ) VALUES (
                    'migration-feedback', 'bug', 'new', 'A durable feedback message',
                    '/', 'GSUBS', NULL, %s, %s, 1, 1, 'pending', 0, 1
                )
                """,
                ("a" * 64, "b" * 64),
            )

        refused = _run_alembic(
            database_url,
            "downgrade",
            "0023_beta_login_promotion",
        )
        assert refused.returncode != 0
        assert "Cannot downgrade product feedback after messages were submitted" in refused.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version",
            ).fetchone() == ("0026_retire_text_models",)
