from __future__ import annotations

import os
import time
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from backend.app.services.financial_records import financial_retention_deadline
from backend.tests.billing_financial_migration_support import (
    EXPIRED_FINANCIAL_AT,
    _insert_durable_purchase,
    _run_alembic,
)


def test_durable_billing_database_guards_and_invoice_provenance() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_billing_guards_{uuid.uuid4().hex[:12]}"
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
    unpaid_purchase_id = uuid.uuid4().hex
    paid_purchase_id = uuid.uuid4().hex
    pending_purchase_id = uuid.uuid4().hex
    unknown_status_purchase_id = uuid.uuid4().hex
    invoice_id = uuid.uuid4().hex
    pending_invoice_id = uuid.uuid4().hex
    reversal_id = uuid.uuid4().hex
    late_invoice_id = uuid.uuid4().hex
    late_reversal_id = uuid.uuid4().hex
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
                VALUES (%s, %s, 'Migration', 'local', 'x', NULL, NULL, 'now', TRUE)
                """,
                (user_id, f"{user_id}@example.com"),
            )
            _insert_durable_purchase(
                connection,
                purchase_id=unpaid_purchase_id,
                user_id=user_id,
                paid=False,
            )

            # REGRESSION: terminal attempts are deletable only through a
            # transaction-local cutoff, bounded independently by database time.
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="cutoff is required",
            ):
                connection.execute(
                    "DELETE FROM credit_purchases WHERE id = %s",
                    (unpaid_purchase_id,),
                )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="retained financial evidence",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(EXPIRED_FINANCIAL_AT + 86_399),),
                    )
                    connection.execute(
                        "DELETE FROM credit_purchases WHERE id = %s",
                        (unpaid_purchase_id,),
                    )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="future",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(int(time.time()) + 3_600),),
                    )
                    connection.execute(
                        "DELETE FROM credit_purchases WHERE id = %s",
                        (unpaid_purchase_id,),
                    )
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                    (str(EXPIRED_FINANCIAL_AT + 86_401),),
                )
                connection.execute(
                    "DELETE FROM credit_purchases WHERE id = %s",
                    (unpaid_purchase_id,),
                )

            for purchase_id in (
                paid_purchase_id,
                pending_purchase_id,
                unknown_status_purchase_id,
            ):
                _insert_durable_purchase(
                    connection,
                    purchase_id=purchase_id,
                    user_id=user_id,
                    paid=True,
                )

            connection.execute(
                """
                INSERT INTO billing_invoices (
                    id, purchase_id, provider, document_kind,
                    document_status, aade_document_type, aade_series,
                    aade_aa, aade_mark, issued_at, recorded_by_user_id,
                    recorded_at, document_snapshot,
                    financial_retention_until, created_at, updated_at
                )
                VALUES (
                    %s, %s, 'aade_etimologio', 'retail_service_receipt',
                    'issued', '11.2', '0', '1', '4000000000000001',
                    %s, %s, %s, %s, 1, %s, %s
                )
                """,
                (
                    invoice_id,
                    paid_purchase_id,
                    EXPIRED_FINANCIAL_AT,
                    user_id,
                    EXPIRED_FINANCIAL_AT,
                    Jsonb({"service_code": "4", "gross_amount_cents": 100}),
                    EXPIRED_FINANCIAL_AT,
                    EXPIRED_FINANCIAL_AT,
                ),
            )
            retained_until = financial_retention_deadline(
                EXPIRED_FINANCIAL_AT,
            )
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM billing_invoices
                WHERE id = %s
                """,
                (invoice_id,),
            ).fetchone() == (retained_until,)

            for column_name, replacement in (
                ("provider", "different_provider"),
                ("document_kind", "different_kind"),
                ("recorded_by_user_id", uuid.uuid4().hex),
                ("recorded_at", EXPIRED_FINANCIAL_AT + 1),
            ):
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="immutable",
                ):
                    with connection.transaction():
                        connection.execute(
                            sql.SQL("UPDATE billing_invoices SET {} = %s WHERE id = %s").format(
                                sql.Identifier(column_name)
                            ),
                            (replacement, invoice_id),
                        )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="transition is invalid",
            ):
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE billing_invoices
                        SET document_status = 'cancelled'
                        WHERE id = %s
                        """,
                        (invoice_id,),
                    )

            connection.execute(
                """
                INSERT INTO billing_invoices (
                    id, purchase_id, provider, document_kind,
                    document_status, aade_document_type, aade_series,
                    aade_aa, aade_mark, issued_at, document_snapshot,
                    financial_retention_until, created_at, updated_at
                )
                VALUES (
                    %s, %s, 'aade_etimologio', 'retail_service_receipt',
                    'pending_manual_issue', NULL, NULL, NULL, NULL, NULL,
                    %s, 1, %s, %s
                )
                """,
                (
                    pending_invoice_id,
                    pending_purchase_id,
                    Jsonb({"service_code": "4", "gross_amount_cents": 100}),
                    EXPIRED_FINANCIAL_AT,
                    EXPIRED_FINANCIAL_AT,
                ),
            )
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM billing_invoices
                WHERE id = %s
                """,
                (pending_invoice_id,),
            ).fetchone() == (retained_until,)
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE billing_invoices
                        SET
                            document_status = 'issued',
                            aade_document_type = '11.2',
                            aade_series = '   ',
                            aade_aa = '2',
                            aade_mark = '4000000000000002',
                            issued_at = %s,
                            recorded_by_user_id = %s,
                            recorded_at = %s
                        WHERE id = %s
                        """,
                        (
                            EXPIRED_FINANCIAL_AT,
                            user_id,
                            EXPIRED_FINANCIAL_AT,
                            pending_invoice_id,
                        ),
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE billing_invoices
                        SET
                            recorded_by_user_id = %s,
                            recorded_at = %s
                        WHERE id = %s
                        """,
                        (
                            user_id,
                            EXPIRED_FINANCIAL_AT,
                            pending_invoice_id,
                        ),
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO billing_invoices (
                            id, purchase_id, provider, document_kind,
                            document_status, document_snapshot,
                            financial_retention_until, created_at, updated_at
                        )
                        VALUES (
                            %s, %s, 'aade_etimologio',
                            'retail_service_receipt', 'unexpected',
                            %s, 1, %s, %s
                        )
                        """,
                        (
                            uuid.uuid4().hex,
                            unknown_status_purchase_id,
                            Jsonb({"service_code": "4"}),
                            EXPIRED_FINANCIAL_AT,
                            EXPIRED_FINANCIAL_AT,
                        ),
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO billing_invoices (
                            id, purchase_id, provider, document_kind,
                            document_status, aade_document_type, aade_series,
                            aade_aa, aade_mark, issued_at,
                            recorded_by_user_id, recorded_at, document_snapshot,
                            financial_retention_until, created_at, updated_at
                        )
                        VALUES (
                            %s, %s, 'aade_etimologio',
                            'retail_service_receipt', 'issued',
                            NULL, '0', '3', '4000000000000003', %s,
                            %s, %s, %s, 1, %s, %s
                        )
                        """,
                        (
                            uuid.uuid4().hex,
                            unknown_status_purchase_id,
                            EXPIRED_FINANCIAL_AT,
                            user_id,
                            EXPIRED_FINANCIAL_AT,
                            Jsonb({"service_code": "4"}),
                            EXPIRED_FINANCIAL_AT,
                            EXPIRED_FINANCIAL_AT,
                        ),
                    )

            connection.execute(
                """
                INSERT INTO billing_invoices (
                    id, purchase_id, provider, document_kind,
                    document_status, aade_document_type, aade_series,
                    aade_aa, aade_mark, issued_at, recorded_by_user_id,
                    recorded_at, document_snapshot,
                    financial_retention_until, created_at, updated_at
                )
                VALUES (
                    %s, %s, 'aade_etimologio', 'retail_service_receipt',
                    'issued', '11.2', '0', '4', '4000000000000004',
                    %s, %s, %s, %s, 1, %s, %s
                )
                """,
                (
                    late_invoice_id,
                    unknown_status_purchase_id,
                    EXPIRED_FINANCIAL_AT,
                    user_id,
                    EXPIRED_FINANCIAL_AT,
                    Jsonb({"service_code": "4"}),
                    EXPIRED_FINANCIAL_AT,
                    EXPIRED_FINANCIAL_AT,
                ),
            )
            late_reversal_at = int(time.time())
            connection.execute(
                """
                INSERT INTO credit_purchase_reversals (
                    id, purchase_id, provider, provider_reversal_id,
                    provider_event_id, provider_event_created, kind,
                    amount_cents, currency, status, active, created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, 'stripe', %s, %s, %s, 'refund',
                    25, 'eur', 'failed', FALSE, %s, %s
                )
                """,
                (
                    late_reversal_id,
                    unknown_status_purchase_id,
                    f"re_{late_reversal_id}",
                    f"evt_{late_reversal_id}",
                    late_reversal_at,
                    late_reversal_at,
                    late_reversal_at,
                ),
            )
            for assignment, message in (
                (
                    "created_at = created_at + 1",
                    "created_at is immutable",
                ),
                (
                    "provider_event_created = provider_event_created - 1",
                    "provider_event_created cannot move backwards",
                ),
                (
                    "updated_at = updated_at - 1",
                    "updated_at cannot move backwards",
                ),
            ):
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match=message,
                ):
                    with connection.transaction():
                        connection.execute(
                            f"""
                            UPDATE credit_purchase_reversals
                            SET {assignment}
                            WHERE id = %s
                            """,
                            (late_reversal_id,),
                        )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="retained financial evidence",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(retained_until + 1),),
                    )
                    connection.execute(
                        "DELETE FROM credit_purchase_reversals WHERE id = %s",
                        (late_reversal_id,),
                    )

            connection.execute(
                """
                INSERT INTO credit_purchase_reversals (
                    id, purchase_id, provider, provider_reversal_id,
                    provider_event_id, provider_event_created, kind,
                    amount_cents, currency, status, active, created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, 'stripe', %s, %s, %s, 'refund',
                    100, 'eur', 'succeeded', TRUE, %s, %s
                )
                """,
                (
                    reversal_id,
                    paid_purchase_id,
                    f"re_{reversal_id}",
                    f"evt_{reversal_id}",
                    EXPIRED_FINANCIAL_AT,
                    EXPIRED_FINANCIAL_AT,
                    EXPIRED_FINANCIAL_AT,
                ),
            )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="retained financial evidence",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(retained_until + 1),),
                    )
                    connection.execute(
                        "DELETE FROM billing_invoices WHERE id = %s",
                        (invoice_id,),
                    )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="retained financial evidence",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(retained_until - 1),),
                    )
                    connection.execute(
                        "DELETE FROM credit_purchase_reversals WHERE id = %s",
                        (reversal_id,),
                    )
            connection.execute(
                """
                UPDATE credit_purchase_reversals
                SET status = 'pending', active = TRUE
                WHERE id = %s
                """,
                (reversal_id,),
            )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="retained financial evidence",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(retained_until + 1),),
                    )
                    connection.execute(
                        "DELETE FROM credit_purchase_reversals WHERE id = %s",
                        (reversal_id,),
                    )
            connection.execute(
                """
                UPDATE credit_purchase_reversals
                SET status = 'succeeded', active = TRUE
                WHERE id = %s
                """,
                (reversal_id,),
            )
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                    (str(retained_until + 1),),
                )
                connection.execute(
                    "DELETE FROM credit_purchase_reversals WHERE id = %s",
                    (reversal_id,),
                )
                connection.execute(
                    "DELETE FROM billing_invoices WHERE id = %s",
                    (invoice_id,),
                )
                connection.execute(
                    "DELETE FROM credit_purchases WHERE id = %s",
                    (paid_purchase_id,),
                )
            assert connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM credit_purchases WHERE id = %s),
                    (SELECT COUNT(*) FROM billing_invoices WHERE id = %s),
                    (SELECT COUNT(*) FROM credit_purchase_reversals WHERE id = %s)
                """,
                (paid_purchase_id, invoice_id, reversal_id),
            ).fetchone() == (0, 0, 0)
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
