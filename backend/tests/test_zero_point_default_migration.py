"""Regression coverage for the database-side zero-credit default."""

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
    database_name = f"gsp_zero_default_{uuid.uuid4().hex[:12]}"
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


def _insert_user(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    user_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO users (
            id, email, name, provider, password_hash, google_sub,
            avatar_url, created_at, email_verified
        )
        VALUES (%s, %s, 'Zero Default', 'local', 'x', NULL, NULL, 'now', TRUE)
        """,
        (user_id, f"{user_id}@example.com"),
    )


def test_zero_credit_default_preserves_existing_wallets_and_safe_downgrade() -> None:
    # REGRESSION: direct/legacy inserts could still receive 1,000 promotional
    # credits even after automatic signup grants were removed from the API.
    with _isolated_database() as (database_url, connection_url):
        before = _run_alembic(
            database_url,
            "upgrade",
            "0018_approved_contract_delivery",
        )
        assert before.returncode == 0, before.stderr

        legacy_user_id = uuid.uuid4().hex
        new_user_id = uuid.uuid4().hex
        downgraded_user_id = uuid.uuid4().hex
        with psycopg.connect(connection_url, autocommit=True) as connection:
            _insert_user(connection, user_id=legacy_user_id)
            connection.execute(
                """
                INSERT INTO user_points (user_id, updated_at)
                VALUES (%s, 1)
                """,
                (legacy_user_id,),
            )
            legacy_balance = connection.execute(
                "SELECT balance FROM user_points WHERE user_id = %s",
                (legacy_user_id,),
            ).fetchone()
            assert legacy_balance == (1000,)

        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            preserved_balance = connection.execute(
                "SELECT balance FROM user_points WHERE user_id = %s",
                (legacy_user_id,),
            ).fetchone()
            assert preserved_balance == (1000,)
            _insert_user(connection, user_id=new_user_id)
            connection.execute(
                """
                INSERT INTO user_points (user_id, updated_at)
                VALUES (%s, 2)
                """,
                (new_user_id,),
            )
            new_balance = connection.execute(
                "SELECT balance FROM user_points WHERE user_id = %s",
                (new_user_id,),
            ).fetchone()
            assert new_balance == (0,)

        downgraded = _run_alembic(
            database_url,
            "downgrade",
            "0018_approved_contract_delivery",
        )
        assert downgraded.returncode == 0, downgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            _insert_user(connection, user_id=downgraded_user_id)
            connection.execute(
                """
                INSERT INTO user_points (user_id, updated_at)
                VALUES (%s, 3)
                """,
                (downgraded_user_id,),
            )
            downgraded_balance = connection.execute(
                "SELECT balance FROM user_points WHERE user_id = %s",
                (downgraded_user_id,),
            ).fetchone()
            assert downgraded_balance == (0,)
