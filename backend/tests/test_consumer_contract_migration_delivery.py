from __future__ import annotations

import os
import subprocess
import time
import uuid

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from backend.tests.consumer_contract_migration_support import (
    _insert_confirmation,
    _insert_purchase,
    _run_alembic,
    _start_alembic,
)


def test_approved_delivery_migration_preserves_pending_evidence_on_downgrade() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_delivery_migration_{uuid.uuid4().hex[:12]}"
    admin_parameters = {
        "dbname": "postgres",
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    try:
        with psycopg.connect(
            **admin_parameters,
            autocommit=True,
        ) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                )
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip(
            "Database role cannot create the isolated migration database",
        )

    database_url = configured_url.set(
        database=database_name,
    ).render_as_string(hide_password=False)
    connection_parameters = {
        "dbname": database_name,
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    user_id = uuid.uuid4().hex
    pending_purchase_id = uuid.uuid4().hex
    approved_purchase_id = uuid.uuid4().hex
    pending_confirmation_id = uuid.uuid4().hex
    approved_confirmation_id = uuid.uuid4().hex
    try:
        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id, email, name, provider, password_hash, google_sub,
                    avatar_url, created_at, email_verified
                )
                VALUES (
                    %s, %s, 'Delivery migration', 'local', 'x',
                    NULL, NULL, 'now', TRUE
                )
                """,
                (user_id, f"{user_id}@example.com"),
            )
            _insert_purchase(
                connection,
                purchase_id=pending_purchase_id,
                user_id=user_id,
            )
            _insert_purchase(
                connection,
                purchase_id=approved_purchase_id,
                user_id=user_id,
            )
            _insert_confirmation(
                connection,
                confirmation_id=pending_confirmation_id,
                purchase_id=pending_purchase_id,
            )

        downgraded = _run_alembic(
            database_url,
            "downgrade",
            "0017_remove_signup_markers",
        )
        assert downgraded.returncode == 0, downgraded.stderr
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0017_remove_signup_markers",
            )
            assert connection.execute(
                """
                SELECT delivery_channel, delivery_status
                FROM billing_contract_confirmations
                WHERE id = %s
                """,
                (pending_confirmation_id,),
            ).fetchone() == (
                "account_vault",
                "available_pending_external_approval",
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=approved_confirmation_id,
                    purchase_id=approved_purchase_id,
                    delivery_status="available_approved",
                )

        reupgraded = _run_alembic(database_url, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stderr
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            _insert_confirmation(
                connection,
                confirmation_id=approved_confirmation_id,
                purchase_id=approved_purchase_id,
                delivery_status="available_approved",
            )
            assert connection.execute(
                """
                SELECT delivery_status
                FROM billing_contract_confirmations
                WHERE id = %s
                """,
                (approved_confirmation_id,),
            ).fetchone() == ("available_approved",)
    finally:
        with psycopg.connect(
            **admin_parameters,
            autocommit=True,
        ) as admin:
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


def test_consumer_contract_downgrade_serializes_concurrent_evidence() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_consumer_race_{uuid.uuid4().hex[:12]}"
    admin_parameters = {
        "dbname": "postgres",
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    try:
        with psycopg.connect(
            **admin_parameters,
            autocommit=True,
        ) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                )
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip(
            "Database role cannot create the isolated migration database",
        )

    database_url = configured_url.set(
        database=database_name,
    ).render_as_string(hide_password=False)
    connection_parameters = {
        "dbname": database_name,
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    user_id = uuid.uuid4().hex
    purchase_id = uuid.uuid4().hex
    confirmation_id = uuid.uuid4().hex
    process: subprocess.Popen[str] | None = None
    try:
        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as setup:
            setup.execute(
                """
                INSERT INTO users (
                    id, email, name, provider, password_hash, google_sub,
                    avatar_url, created_at, email_verified
                )
                VALUES (%s, %s, 'Migration', 'local', 'x', NULL, NULL, 'now', TRUE)
                """,
                (user_id, f"{user_id}@example.com"),
            )
            _insert_purchase(
                setup,
                purchase_id=purchase_id,
                user_id=user_id,
            )

        with psycopg.connect(**connection_parameters) as writer:
            # Match the withdrawal/idempotency flow's lock order before
            # touching its required confirmation evidence.
            writer.execute(
                "SELECT COUNT(*) FROM billing_withdrawal_requests",
            )
            process = _start_alembic(
                database_url,
                "downgrade",
                "0013_durable_billing_records",
            )
            deadline = time.monotonic() + 10
            waiting_on_lock = False
            with psycopg.connect(
                **admin_parameters,
                autocommit=True,
            ) as observer:
                while time.monotonic() < deadline:
                    waiting_on_lock = bool(
                        observer.execute(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE datname = %s
                                  AND wait_event_type = 'Lock'
                            )
                            """,
                            (database_name,),
                        ).fetchone()[0]
                    )
                    if waiting_on_lock or process.poll() is not None:
                        break
                    time.sleep(0.05)
            assert waiting_on_lock, "Downgrade did not serialize on the evidence writer"
            _insert_confirmation(
                writer,
                confirmation_id=confirmation_id,
                purchase_id=purchase_id,
                delivery_status="available_approved",
            )
            writer.commit()

        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode != 0, stdout
        assert (
            "Cannot downgrade approved contract-confirmation delivery while approved durable evidence exists."
        ) in stderr
        current = _run_alembic(database_url, "current")
        assert current.returncode == 0, current.stderr
        assert "0027_restore_beta_promo_cap (head)" in current.stdout
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_contract_confirmations",
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT to_regclass('public.billing_withdrawal_requests')",
            ).fetchone() == ("billing_withdrawal_requests",)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
        with psycopg.connect(
            **admin_parameters,
            autocommit=True,
        ) as admin:
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
