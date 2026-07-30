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

from backend.app.services.financial_records import financial_retention_deadline

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_AT = 1_800_000_000
LATER_RECORDED_AT = REFERENCE_AT + 366 * 24 * 60 * 60


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
def _isolated_database(
    prefix: str,
) -> Iterator[tuple[str, str]]:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    admin_url = configured_url.set(
        drivername="postgresql",
        database="postgres",
    ).render_as_string(hide_password=False)
    try:
        with psycopg.connect(
            admin_url,
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
    connection_url = configured_url.set(
        drivername="postgresql",
        database=database_name,
    ).render_as_string(hide_password=False)
    try:
        yield database_url, connection_url
    finally:
        with psycopg.connect(
            admin_url,
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


def _insert_user_and_paid_purchase(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    user_id: str,
    purchase_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO users (
            id, email, name, provider, password_hash, google_sub,
            avatar_url, created_at, email_verified
        )
        VALUES (%s, %s, 'Actor Audit', 'local', 'x', NULL, NULL, 'now', TRUE)
        """,
        (user_id, f"{user_id}@example.com"),
    )
    connection.execute(
        """
        INSERT INTO credit_purchases (
            id, user_id, provider, package_key, credits,
            amount_eur_cents, currency, idempotency_key,
            checkout_session_id, checkout_url, payment_intent_id,
            integration_identifier, status, fulfilled_at,
            refunded_amount_cents, dispute_active, reversed_credits,
            reversal_debt_credits, reversed_amount_cents, snapshot,
            payment_snapshot, customer_snapshot, tax_snapshot,
            financial_retention_until, error, created_at, updated_at
        )
        VALUES (
            %s, %s, 'stripe', 'starter', 100,
            100, 'eur', %s, %s, NULL, %s,
            'gsubs_credits_v1', 'paid', %s,
            0, FALSE, 0, 0, 0, %s,
            %s, NULL, NULL, 1, NULL, %s, %s
        )
        """,
        (
            purchase_id,
            user_id,
            f"actor-audit-{purchase_id}",
            f"cs_{purchase_id}",
            f"pi_{purchase_id}",
            REFERENCE_AT,
            Jsonb({"catalog_version": "actor-audit-migration-test"}),
            Jsonb(
                {
                    "payment_intent_id": f"pi_{purchase_id}",
                    "stripe_event_created": REFERENCE_AT,
                }
            ),
            REFERENCE_AT,
            REFERENCE_AT,
        ),
    )


def _insert_pre_0015_invoice(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    invoice_id: str,
    purchase_id: str,
    document_status: str,
) -> None:
    terminal = document_status in {"issued", "cancelled"}
    connection.execute(
        """
        INSERT INTO billing_invoices (
            id, purchase_id, provider, document_kind, document_status,
            aade_document_type, aade_series, aade_aa, aade_mark, issued_at,
            document_snapshot, financial_retention_until, created_at,
            updated_at
        )
        VALUES (
            %s, %s, 'aade_etimologio', 'retail_service_receipt', %s,
            %s, %s, %s, %s, %s, %s, 1, %s, %s
        )
        """,
        (
            invoice_id,
            purchase_id,
            document_status,
            "11.2" if terminal else None,
            "0" if terminal else None,
            "1" if terminal else None,
            f"4{invoice_id[:15]}" if terminal else None,
            REFERENCE_AT if terminal else None,
            Jsonb({"service_code": "4"}),
            REFERENCE_AT,
            REFERENCE_AT,
        ),
    )


def _function_definition(
    connection: psycopg.Connection[tuple[object, ...]],
    function_name: str,
) -> str:
    definition = connection.execute(
        "SELECT pg_get_functiondef(%s::regprocedure)",
        (f"public.{function_name}()",),
    ).fetchone()
    assert definition is not None
    return str(definition[0])


def _issued_identity_constraint(
    connection: psycopg.Connection[tuple[object, ...]],
) -> str:
    definition = connection.execute(
        """
        SELECT pg_get_constraintdef(constraint_record.oid, TRUE)
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid =
              'public.billing_invoices'::regclass
          AND constraint_record.conname =
              'chk_billing_invoices_issued_identity'
        """
    ).fetchone()
    assert definition is not None
    return str(definition[0])


def test_existing_0014_pending_schema_upgrades_and_cleanly_downgrades() -> None:
    with _isolated_database("gsp_actor_existing") as (
        database_url,
        connection_url,
    ):
        before = _run_alembic(
            database_url,
            "upgrade",
            "0014_consumer_contract_records",
        )
        assert before.returncode == 0, before.stderr
        user_id = uuid.uuid4().hex
        purchase_id = uuid.uuid4().hex
        invoice_id = uuid.uuid4().hex
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            _insert_user_and_paid_purchase(
                connection,
                user_id=user_id,
                purchase_id=purchase_id,
            )
            _insert_pre_0015_invoice(
                connection,
                invoice_id=invoice_id,
                purchase_id=purchase_id,
                document_status="pending_manual_issue",
            )
            prepare_before = _function_definition(
                connection,
                "gsubs_prepare_billing_invoice",
            )
            immutable_before = _function_definition(
                connection,
                "gsubs_enforce_billing_invoice_immutability",
            )
            constraint_before = _issued_identity_constraint(connection)

        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0020_usage_results",)
            assert connection.execute(
                """
                SELECT recorded_by_user_id, recorded_at
                FROM billing_invoices
                WHERE id = %s
                """,
                (invoice_id,),
            ).fetchone() == (None, None)
            assert "COALESCE(NEW.recorded_at, 0)" in _function_definition(
                connection,
                "gsubs_prepare_billing_invoice",
            )
            assert "recorded_by_user_id is immutable" in _function_definition(
                connection,
                "gsubs_enforce_billing_invoice_immutability",
            )
            assert "recorded_by_user_id" in _issued_identity_constraint(
                connection
            )
            assert connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.key_column_usage AS usage
                JOIN information_schema.table_constraints AS constraint_info
                  ON constraint_info.constraint_catalog =
                     usage.constraint_catalog
                 AND constraint_info.constraint_schema =
                     usage.constraint_schema
                 AND constraint_info.constraint_name =
                     usage.constraint_name
                WHERE usage.table_schema = 'public'
                  AND usage.table_name = 'billing_invoices'
                  AND usage.column_name = 'recorded_by_user_id'
                  AND constraint_info.constraint_type = 'FOREIGN KEY'
                """
            ).fetchone() == (0,)

        downgraded = _run_alembic(
            database_url,
            "downgrade",
            "0014_consumer_contract_records",
        )
        assert downgraded.returncode == 0, downgraded.stderr
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            assert _function_definition(
                connection,
                "gsubs_prepare_billing_invoice",
            ) == prepare_before
            assert _function_definition(
                connection,
                "gsubs_enforce_billing_invoice_immutability",
            ) == immutable_before
            assert _issued_identity_constraint(connection) == constraint_before
            assert connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'billing_invoices'
                  AND column_name IN (
                      'recorded_by_user_id',
                      'recorded_at'
                  )
                """
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_invoices WHERE id = %s",
                (invoice_id,),
            ).fetchone() == (1,)

        reupgraded = _run_alembic(database_url, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stderr


@pytest.mark.parametrize("document_status", ("issued", "cancelled"))
def test_existing_0014_terminal_schema_upgrade_refuses_without_attribution(
    document_status: str,
) -> None:
    with _isolated_database("gsp_actor_refuse") as (
        database_url,
        connection_url,
    ):
        before = _run_alembic(
            database_url,
            "upgrade",
            "0014_consumer_contract_records",
        )
        assert before.returncode == 0, before.stderr
        user_id = uuid.uuid4().hex
        purchase_id = uuid.uuid4().hex
        invoice_id = uuid.uuid4().hex
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            _insert_user_and_paid_purchase(
                connection,
                user_id=user_id,
                purchase_id=purchase_id,
            )
            _insert_pre_0015_invoice(
                connection,
                invoice_id=invoice_id,
                purchase_id=purchase_id,
                document_status=document_status,
            )

        upgrade = _run_alembic(database_url, "upgrade", "head")

        assert upgrade.returncode != 0
        assert (
            "pre-existing issued or cancelled invoices lack truthful actor "
            "attribution"
        ) in upgrade.stderr
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0014_consumer_contract_records",)
            assert connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'billing_invoices'
                  AND column_name IN (
                      'recorded_by_user_id',
                      'recorded_at'
                  )
                """
            ).fetchone() == (0,)
            assert connection.execute(
                """
                SELECT document_status
                FROM billing_invoices
                WHERE id = %s
                """,
                (invoice_id,),
            ).fetchone() == (document_status,)


def test_fresh_head_enforces_actor_audit_and_refuses_destructive_downgrade() -> None:
    with _isolated_database("gsp_actor_fresh") as (
        database_url,
        connection_url,
    ):
        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        user_id = uuid.uuid4().hex
        purchase_id = uuid.uuid4().hex
        invoice_id = uuid.uuid4().hex
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            _insert_user_and_paid_purchase(
                connection,
                user_id=user_id,
                purchase_id=purchase_id,
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
                    %s, %s, 'aade_etimologio',
                    'retail_service_receipt', 'issued', '11.2', '0',
                    '1', %s, %s, %s, %s, %s, 1, %s, %s
                )
                """,
                (
                    invoice_id,
                    purchase_id,
                    f"4{invoice_id[:15]}",
                    REFERENCE_AT,
                    user_id,
                    LATER_RECORDED_AT,
                    Jsonb({"service_code": "4"}),
                    REFERENCE_AT,
                    REFERENCE_AT,
                ),
            )
            assert connection.execute(
                """
                SELECT recorded_by_user_id, recorded_at,
                       financial_retention_until
                FROM billing_invoices
                WHERE id = %s
                """,
                (invoice_id,),
            ).fetchone() == (
                user_id,
                LATER_RECORDED_AT,
                financial_retention_deadline(LATER_RECORDED_AT),
            )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="recorded_by_user_id is immutable",
            ):
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE billing_invoices
                        SET recorded_by_user_id = %s
                        WHERE id = %s
                        """,
                        (uuid.uuid4().hex, invoice_id),
                    )

        downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0014_consumer_contract_records",
        )

        assert downgrade.returncode != 0
        assert (
            "terminal or actor-audit financial evidence exists"
            in downgrade.stderr
        )
        with psycopg.connect(
            connection_url,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0020_usage_results",)
            assert connection.execute(
                """
                SELECT recorded_by_user_id, recorded_at
                FROM billing_invoices
                WHERE id = %s
                """,
                (invoice_id,),
            ).fetchone() == (user_id, LATER_RECORDED_AT)
