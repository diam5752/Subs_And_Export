"""Migration contract for retiring the unused text-generation catalog."""

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


def _run_alembic(
    database_url: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
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
        )
    )
    database_name = f"gsp_retired_models_{uuid.uuid4().hex[:12]}"
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


def test_retirement_removes_unused_rows_and_preserves_audit_references() -> None:
    with _isolated_database() as (database_url, connection_url):
        before_retirement = _run_alembic(database_url, "upgrade", "0025")
        assert before_retirement.returncode == 0, before_retirement.stderr

        with psycopg.connect(connection_url, autocommit=True) as connection:
            candidate = connection.execute(
                """
                SELECT id
                FROM ai_models
                WHERE id LIKE 'gpt-%'
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
            assert candidate is not None
            referenced_model_id = candidate[0]
            connection.execute(
                """
                INSERT INTO token_usage (
                    job_id, model_id, prompt_tokens, completion_tokens,
                    total_tokens, cost, timestamp
                ) VALUES (NULL, %s, 10, 5, 15, 0.01, 1)
                """,
                (referenced_model_id,),
            )

        retired = _run_alembic(database_url, "upgrade", "head")
        assert retired.returncode == 0, retired.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0027_restore_beta_promo_cap",)
            assert connection.execute(
                """
                SELECT id, active
                FROM ai_models
                WHERE id LIKE 'gpt-%'
                ORDER BY id
                """
            ).fetchall() == [(referenced_model_id, False)]

        downgraded = _run_alembic(database_url, "downgrade", "0025")
        assert downgraded.returncode == 0, downgraded.stderr
        reupgraded = _run_alembic(database_url, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                """
                SELECT id, active
                FROM ai_models
                WHERE id LIKE 'gpt-%'
                ORDER BY id
                """
            ).fetchall() == [(referenced_model_id, False)]
