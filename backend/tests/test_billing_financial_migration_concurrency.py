from __future__ import annotations

import os
import subprocess
import time
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from backend.tests.billing_financial_migration_support import (
    EXPIRED_FINANCIAL_AT,
    _insert_durable_purchase,
    _run_alembic,
    _start_alembic,
)


def test_durable_billing_downgrade_serializes_parent_first_writer() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_billing_race_{uuid.uuid4().hex[:12]}"
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
        pytest.skip("Database role cannot create the isolated migration database")

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
    invoice_id = uuid.uuid4().hex
    process: subprocess.Popen[str] | None = None
    try:
        upgraded = _run_alembic(
            database_url,
            "upgrade",
            "0013_durable_billing_records",
        )
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
            _insert_durable_purchase(
                setup,
                purchase_id=purchase_id,
                user_id=user_id,
                paid=False,
            )

        with psycopg.connect(**connection_parameters) as writer:
            writer.execute(
                """
                SELECT id
                FROM credit_purchases
                WHERE id = %s
                FOR UPDATE
                """,
                (purchase_id,),
            )
            process = _start_alembic(
                database_url,
                "downgrade",
                "0012_google_avatar_url",
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
            assert waiting_on_lock, "Downgrade did not wait on the parent-first writer"

            # REGRESSION: the downgrade must wait on the parent before taking
            # child locks. The writer can therefore finish its normal
            # purchase-then-invoice order without a deadlock; the serialized
            # downgrade then observes and preserves the new evidence.
            writer.execute(
                """
                INSERT INTO billing_invoices (
                    id, purchase_id, provider, document_kind,
                    document_status, document_snapshot,
                    financial_retention_until, created_at, updated_at
                )
                VALUES (
                    %s, %s, 'aade_etimologio',
                    'retail_service_receipt', 'pending_manual_issue',
                    %s, 1, %s, %s
                )
                """,
                (
                    invoice_id,
                    purchase_id,
                    Jsonb({"service_code": "4"}),
                    EXPIRED_FINANCIAL_AT,
                    EXPIRED_FINANCIAL_AT,
                ),
            )
            writer.commit()

        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode != 0, stdout
        assert "durable paid financial records exist" in stderr
        assert "deadlock detected" not in stderr.lower()
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_invoices WHERE id = %s",
                (invoice_id,),
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT to_regclass('public.credit_purchase_reversals')",
            ).fetchone() == ("credit_purchase_reversals",)
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
