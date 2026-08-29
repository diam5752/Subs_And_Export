"""Migration regression coverage for temporary usage-result replay storage."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(
    database_url: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *arguments],
        cwd=BACKEND_ROOT,
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
        )
    )
    database_name = f"gsp_usage_results_{uuid.uuid4().hex[:12]}"
    admin_url = configured_url.set(
        drivername="postgresql",
        database="postgres",
    ).render_as_string(hide_password=False)
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                )
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("Database role cannot create the isolated migration database")

    database_url = configured_url.set(
        database=database_name,
    ).render_as_string(hide_password=False)
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
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name),
                )
            )


def _insert_user_job_and_ledger(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    user_id: str,
    job_id: str,
    ledger_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO users (
            id, email, name, provider, password_hash, google_sub,
            avatar_url, created_at, email_verified
        )
        VALUES (%s, %s, 'Usage Result', 'local', 'x', NULL, NULL, 'now', TRUE)
        ON CONFLICT (id) DO NOTHING
        """,
        (user_id, f"{user_id}@example.com"),
    )
    connection.execute(
        """
        INSERT INTO jobs (
            id, user_id, status, created_at, updated_at, progress,
            message, result_data
        )
        VALUES (%s, %s, 'processing', 1, 1, 0, NULL, NULL)
        """,
        (job_id, user_id),
    )
    connection.execute(
        """
        INSERT INTO usage_ledger (
            id, user_id, job_id, action, provider, status, created_at, updated_at
        )
        VALUES (%s, %s, %s, 'transcription', 'elevenlabs', 'dispatched', 1, 1)
        """,
        (ledger_id, user_id, job_id),
    )


def _insert_result(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    ledger_id: str,
    job_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO usage_results (
            ledger_id, job_id, payload, created_at, updated_at
        )
        VALUES (%s, %s, %s, 2, 2)
        """,
        (
            ledger_id,
            job_id,
            Jsonb({"provider_request_id": "request-1", "segments": []}),
        ),
    )


def test_usage_result_migration_preserves_payload_and_cascades() -> None:
    # REGRESSION: a successful provider response could be lost before the job
    # finalized, causing retries to dispatch and charge the provider twice.
    with _isolated_database() as (database_url, connection_url):
        before = _run_alembic(
            database_url,
            "upgrade",
            "0019_zero_wallet_default",
        )
        assert before.returncode == 0, before.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.usage_results')"
            ).fetchone() == (None,)

        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr

        user_id = uuid.uuid4().hex
        first_job_id = f"job-{uuid.uuid4().hex}"
        first_ledger_id = uuid.uuid4().hex
        second_job_id = f"job-{uuid.uuid4().hex}"
        second_ledger_id = uuid.uuid4().hex
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0027_restore_beta_promo_cap",)
            assert connection.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'usage_results'
                ORDER BY ordinal_position
                """
            ).fetchall() == [
                ("ledger_id", "character varying", "NO"),
                ("job_id", "character varying", "NO"),
                ("payload", "jsonb", "NO"),
                ("created_at", "integer", "NO"),
                ("updated_at", "integer", "NO"),
            ]
            assert connection.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'usage_results'
                  AND indexname = 'ix_usage_results_job_id'
                """
            ).fetchone() is not None

            _insert_user_job_and_ledger(
                connection,
                user_id=user_id,
                job_id=first_job_id,
                ledger_id=first_ledger_id,
            )
            _insert_result(
                connection,
                ledger_id=first_ledger_id,
                job_id=first_job_id,
            )
            assert connection.execute(
                "SELECT payload FROM usage_results WHERE ledger_id = %s",
                (first_ledger_id,),
            ).fetchone() == (
                {
                    "provider_request_id": "request-1",
                    "segments": [],
                },
            )

            connection.execute(
                "DELETE FROM usage_ledger WHERE id = %s",
                (first_ledger_id,),
            )
            assert connection.execute(
                "SELECT COUNT(*) FROM usage_results"
            ).fetchone() == (0,)

            _insert_user_job_and_ledger(
                connection,
                user_id=user_id,
                job_id=second_job_id,
                ledger_id=second_ledger_id,
            )
            _insert_result(
                connection,
                ledger_id=second_ledger_id,
                job_id=second_job_id,
            )
            connection.execute(
                "DELETE FROM jobs WHERE id = %s",
                (second_job_id,),
            )
            assert connection.execute(
                "SELECT COUNT(*) FROM usage_results"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT job_id FROM usage_ledger WHERE id = %s",
                (second_ledger_id,),
            ).fetchone() == (None,)

        downgraded = _run_alembic(
            database_url,
            "downgrade",
            "0019_zero_wallet_default",
        )
        assert downgraded.returncode == 0, downgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.usage_results')"
            ).fetchone() == (None,)
