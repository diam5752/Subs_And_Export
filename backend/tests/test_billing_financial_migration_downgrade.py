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

from backend.app.services.financial_records import financial_retention_deadline
from backend.tests.billing_financial_migration_support import (
    REFERENCE_AT,
    _run_alembic,
    _start_alembic,
)


def test_durable_billing_migration_rejects_truncate_and_downgrades_cleanly() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_billing_truncate_{uuid.uuid4().hex[:12]}"
    admin_parameters = {
        "dbname": "postgres",
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    try:
        with psycopg.connect(**admin_parameters, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                )
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("Database role cannot create the isolated migration database")

    database_url = configured_url.set(database=database_name).render_as_string(
        hide_password=False,
    )
    try:
        upgraded = _run_alembic(
            database_url,
            "upgrade",
            "0013_durable_billing_records",
        )
        assert upgraded.returncode == 0, upgraded.stderr

        with psycopg.connect(
            dbname=database_name,
            user=configured_url.username,
            password=configured_url.password,
            host=configured_url.host,
            port=configured_url.port,
            autocommit=True,
        ) as connection:
            for table_name in (
                "credit_purchases",
                "billing_invoices",
                "credit_purchase_reversals",
            ):
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="durable financial evidence",
                ):
                    connection.execute(
                        sql.SQL("TRUNCATE TABLE {} CASCADE").format(
                            sql.Identifier(table_name),
                        )
                    )

        downgraded = _run_alembic(
            database_url,
            "downgrade",
            "0012_google_avatar_url",
        )
        assert downgraded.returncode == 0, downgraded.stderr
    finally:
        with psycopg.connect(**admin_parameters, autocommit=True) as admin:
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


def test_durable_billing_downgrade_serializes_concurrent_financial_evidence() -> None:
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
        with psycopg.connect(**admin_parameters, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                )
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("Database role cannot create the isolated migration database")

    database_url = configured_url.set(database=database_name).render_as_string(
        hide_password=False,
    )
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
            setup.execute(
                """
                INSERT INTO credit_purchases (
                    id, user_id, provider, package_key, credits,
                    amount_eur_cents, currency, idempotency_key,
                    checkout_session_id, checkout_url, payment_intent_id,
                    integration_identifier, status, fulfilled_at,
                    refunded_amount_cents, dispute_active, reversed_credits,
                    reversal_debt_credits, snapshot, error, created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, 'stripe', 'starter', 100,
                    100, 'eur', %s, %s, NULL, NULL,
                    %s, 'checkout_created', NULL,
                    0, FALSE, 0, 0, %s, NULL, %s, %s
                )
                """,
                (
                    purchase_id,
                    user_id,
                    f"race-{purchase_id}",
                    f"cs_{purchase_id}",
                    f"gsubs_credits_{purchase_id[:8]}",
                    Jsonb(
                        {
                            "catalog_version": "migration-race",
                            "package_key": "starter",
                        }
                    ),
                    REFERENCE_AT,
                    REFERENCE_AT,
                ),
            )

        with psycopg.connect(**connection_parameters) as writer:
            writer.execute(
                """
                INSERT INTO billing_invoices (
                    id, purchase_id, document_status, aade_document_type,
                    aade_series, aade_aa, aade_mark, issued_at,
                    document_snapshot, financial_retention_until,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, 'pending_manual_issue', NULL,
                    NULL, NULL, NULL, NULL, %s, %s, %s, %s
                )
                """,
                (
                    invoice_id,
                    purchase_id,
                    Jsonb(
                        {
                            "source_purchase_id": purchase_id,
                            "record_origin": "concurrent-writer-test",
                        }
                    ),
                    financial_retention_deadline(REFERENCE_AT),
                    REFERENCE_AT,
                    REFERENCE_AT,
                ),
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
            assert waiting_on_lock, "Downgrade did not serialize on the financial-evidence writer"
            writer.commit()

        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode != 0, stdout
        assert "durable paid financial records exist" in stderr
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_invoices",
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT to_regclass('public.credit_purchase_reversals')",
            ).fetchone() == ("credit_purchase_reversals",)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
        with psycopg.connect(**admin_parameters, autocommit=True) as admin:
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


def test_durable_billing_migration_allows_clean_unpaid_legacy_downgrade() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_billing_unpaid_{uuid.uuid4().hex[:12]}"
    admin_parameters = {
        "dbname": "postgres",
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    try:
        with psycopg.connect(**admin_parameters, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("Database role cannot create the isolated migration database")

    database_url = configured_url.set(database=database_name).render_as_string(hide_password=False)
    user_id = uuid.uuid4().hex
    purchase_id = uuid.uuid4().hex
    try:
        before = _run_alembic(
            database_url,
            "upgrade",
            "0012_google_avatar_url",
        )
        assert before.returncode == 0, before.stderr

        with psycopg.connect(
            dbname=database_name,
            user=configured_url.username,
            password=configured_url.password,
            host=configured_url.host,
            port=configured_url.port,
        ) as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id,
                    email,
                    name,
                    provider,
                    password_hash,
                    google_sub,
                    avatar_url,
                    created_at,
                    email_verified
                )
                VALUES (%s, %s, %s, 'local', %s, NULL, NULL, %s, TRUE)
                """,
                (
                    user_id,
                    f"{user_id}@example.com",
                    "Unpaid migration",
                    "x",
                    "now",
                ),
            )
            connection.execute(
                """
                INSERT INTO credit_purchases (
                    id,
                    user_id,
                    provider,
                    package_key,
                    credits,
                    amount_eur_cents,
                    currency,
                    idempotency_key,
                    checkout_session_id,
                    checkout_url,
                    payment_intent_id,
                    integration_identifier,
                    status,
                    fulfilled_at,
                    refunded_amount_cents,
                    dispute_active,
                    reversed_credits,
                    reversal_debt_credits,
                    snapshot,
                    error,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, 'stripe', 'starter', 100, 100, 'eur',
                    %s, %s, NULL, NULL, %s, 'checkout_created', NULL,
                    0, FALSE, 0, 0, %s, NULL, %s, %s
                )
                """,
                (
                    purchase_id,
                    user_id,
                    f"unpaid-{purchase_id}",
                    f"cs_{purchase_id}",
                    f"gsubs_credits_{purchase_id[:8]}",
                    Jsonb(
                        {
                            "catalog_version": "legacy",
                            "package_key": "starter",
                        }
                    ),
                    REFERENCE_AT,
                    REFERENCE_AT,
                ),
            )
            connection.commit()

        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(
            dbname=database_name,
            user=configured_url.username,
            password=configured_url.password,
            host=configured_url.host,
            port=configured_url.port,
        ) as connection:
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM credit_purchases
                WHERE id = %s
                """,
                (purchase_id,),
            ).fetchone() == (REFERENCE_AT + 86_400,)

        # A linked checkout attempt with no payment, invoice, snapshot or
        # reversal can safely return to the legacy schema.
        downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0012_google_avatar_url",
        )
        assert downgrade.returncode == 0, downgrade.stderr

        with psycopg.connect(
            dbname=database_name,
            user=configured_url.username,
            password=configured_url.password,
            host=configured_url.host,
            port=configured_url.port,
        ) as connection:
            assert connection.execute(
                """
                SELECT user_id, status, fulfilled_at, payment_intent_id
                FROM credit_purchases
                WHERE id = %s
                """,
                (purchase_id,),
            ).fetchone() == (
                user_id,
                "checkout_created",
                None,
                None,
            )
            assert (
                connection.execute(
                    """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'credit_purchases'
                  AND column_name = 'payment_snapshot'
                """
                ).fetchone()
                is None
            )
    finally:
        with psycopg.connect(**admin_parameters, autocommit=True) as admin:
            admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
