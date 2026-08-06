"""Direct contracts for the cancelling-job-status migration."""

from __future__ import annotations

import importlib
import os
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

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
        cwd=Path(__file__).resolve().parents[1],
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
    database_name = f"gsp_cancelling_status_{uuid.uuid4().hex[:12]}"
    admin_url = configured_url.set(
        drivername="postgresql",
        database="postgres",
    ).render_as_string(hide_password=False)
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                ),
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
                ),
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
        VALUES (%s, %s, 'Cancellation Migration', 'local', 'x', NULL, NULL, 'now', TRUE)
        """,
        (user_id, f"{user_id}@example.com"),
    )


def _insert_job(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    job_id: str,
    user_id: str,
    status: str,
) -> None:
    connection.execute(
        """
        INSERT INTO jobs (
            id, user_id, status, created_at, updated_at, progress,
            message, result_data
        )
        VALUES (%s, %s, %s, 1, 1, 0, NULL, NULL)
        """,
        (job_id, user_id, status),
    )


def _jobs_status_constraint(
    connection: psycopg.Connection[tuple[object, ...]],
) -> str:
    definition = connection.execute(
        """
        SELECT pg_get_constraintdef(constraint_record.oid, TRUE)
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = 'public.jobs'::regclass
          AND constraint_record.conname = 'chk_jobs_status'
        """,
    ).fetchone()
    assert definition is not None
    return str(definition[0])


def _migration_with_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, MagicMock]:
    migration = importlib.import_module(
        "backend.alembic.versions.0022_cancelling_job_status",
    )
    operation = MagicMock()
    monkeypatch.setattr(migration, "op", operation)
    return migration, operation


def test_cancelling_job_status_upgrade_replaces_status_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration, operation = _migration_with_operation(monkeypatch)

    migration.upgrade()

    assert operation.mock_calls == [
        call.drop_constraint("chk_jobs_status", "jobs", type_="check"),
        call.create_check_constraint(
            "chk_jobs_status",
            "jobs",
            "status IN ('pending','processing','cancelling','completed','failed','cancelled')",
        ),
    ]


def test_cancelling_job_status_downgrade_restores_previous_constraint_when_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration, operation = _migration_with_operation(monkeypatch)
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = 0
    operation.get_bind.return_value = connection

    migration.downgrade()

    query = connection.execute.call_args.args[0]
    assert "status = 'cancelling'" in str(query)
    operation.get_bind.assert_called_once_with()
    connection.execute.assert_called_once_with(query)
    operation.drop_constraint.assert_called_once_with(
        "chk_jobs_status",
        "jobs",
        type_="check",
    )
    operation.create_check_constraint.assert_called_once_with(
        "chk_jobs_status",
        "jobs",
        "status IN ('pending','processing','completed','failed','cancelled')",
    )


def test_cancelling_job_status_downgrade_refuses_unfinished_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration, operation = _migration_with_operation(monkeypatch)
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = 1
    operation.get_bind.return_value = connection

    with pytest.raises(
        RuntimeError,
        match="job cancellation cleanup is unfinished",
    ):
        migration.downgrade()

    operation.drop_constraint.assert_not_called()
    operation.create_check_constraint.assert_not_called()


def test_cancelling_job_status_postgresql_downgrade_is_transactional() -> None:
    # REGRESSION: a failed downgrade must not advance the Alembic revision or
    # restore the legacy constraint while cancellation cleanup remains active.
    with _isolated_database() as (database_url, connection_url):
        before = _run_alembic(
            database_url,
            "upgrade",
            "0021_remove_gcs_uploads",
        )
        assert before.returncode == 0, before.stderr

        user_id = uuid.uuid4().hex
        updated_job_id = f"updated-{uuid.uuid4().hex}"
        inserted_job_id = f"inserted-{uuid.uuid4().hex}"
        with psycopg.connect(connection_url, autocommit=True) as connection:
            _insert_user(connection, user_id=user_id)
            _insert_job(
                connection,
                job_id=updated_job_id,
                user_id=user_id,
                status="pending",
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_job(
                    connection,
                    job_id=inserted_job_id,
                    user_id=user_id,
                    status="cancelling",
                )
            assert "cancelling" not in _jobs_status_constraint(connection)

        upgraded = _run_alembic(
            database_url,
            "upgrade",
            "0022_cancelling_job_status",
        )
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            _insert_job(
                connection,
                job_id=inserted_job_id,
                user_id=user_id,
                status="cancelling",
            )
            connection.execute(
                "UPDATE jobs SET status = 'cancelling' WHERE id = %s",
                (updated_job_id,),
            )
            assert connection.execute(
                "SELECT status FROM jobs ORDER BY id",
            ).fetchall() == [("cancelling",), ("cancelling",)]
            assert "cancelling" in _jobs_status_constraint(connection)

        rejected = _run_alembic(
            database_url,
            "downgrade",
            "0021_remove_gcs_uploads",
        )
        assert rejected.returncode != 0
        assert "job cancellation cleanup is unfinished" in rejected.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version",
            ).fetchone() == ("0022_cancelling_job_status",)
            assert "cancelling" in _jobs_status_constraint(connection)
            assert connection.execute(
                "SELECT status FROM jobs ORDER BY id",
            ).fetchall() == [("cancelling",), ("cancelling",)]
            connection.execute(
                "UPDATE jobs SET status = 'cancelled' WHERE status = 'cancelling'",
            )

        downgraded = _run_alembic(
            database_url,
            "downgrade",
            "0021_remove_gcs_uploads",
        )
        assert downgraded.returncode == 0, downgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version",
            ).fetchone() == ("0021_remove_gcs_uploads",)
            assert "cancelling" not in _jobs_status_constraint(connection)
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE jobs SET status = 'cancelling' WHERE id = %s",
                    (updated_job_id,),
                )
            assert connection.execute(
                "SELECT status FROM jobs WHERE id = %s",
                (updated_job_id,),
            ).fetchone() == ("cancelled",)

        reupgraded = _run_alembic(
            database_url,
            "upgrade",
            "0022_cancelling_job_status",
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version",
            ).fetchone() == ("0022_cancelling_job_status",)
            assert "cancelling" in _jobs_status_constraint(connection)
            connection.execute(
                "UPDATE jobs SET status = 'cancelling' WHERE id = %s",
                (updated_job_id,),
            )
            assert connection.execute(
                "SELECT status FROM jobs WHERE id = %s",
                (updated_job_id,),
            ).fetchone() == ("cancelling",)
