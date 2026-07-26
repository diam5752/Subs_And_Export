from __future__ import annotations

import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_AT = 1_785_066_000
DIRECT_PAYMENT_AT = 1_830_000_000
EXPIRED_FINANCIAL_AT = 1_577_836_800


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *arguments],
        cwd=BACKEND_ROOT,
        env={**os.environ, "GSP_DATABASE_URL": database_url},
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _start_alembic(
    database_url: str,
    *arguments: str,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["alembic", *arguments],
        cwd=BACKEND_ROOT,
        env={**os.environ, "GSP_DATABASE_URL": database_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _insert_durable_purchase(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    purchase_id: str,
    user_id: str,
    paid: bool,
    recorded_at: int = EXPIRED_FINANCIAL_AT,
) -> None:
    payment_intent_id = f"pi_{purchase_id}" if paid else None
    payment_snapshot = (
        Jsonb(
            {
                "checkout_session_id": f"cs_{purchase_id}",
                "payment_intent_id": payment_intent_id,
                "payment_status": "paid",
            }
        )
        if paid
        else None
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
            %s, %s, %s, 0, FALSE, 0, 0, 0, %s,
            %s, NULL, NULL, %s, NULL, %s, %s
        )
        """,
        (
            purchase_id,
            user_id,
            f"migration-{purchase_id}",
            f"cs_{purchase_id}",
            payment_intent_id,
            f"gsubs_credits_{purchase_id[:8]}",
            "paid" if paid else "failed",
            recorded_at if paid else None,
            Jsonb({"catalog_version": "migration-test"}),
            payment_snapshot,
            1 if paid else recorded_at + 86_400,
            recorded_at,
            recorded_at,
        ),
    )


def _start_alembic(
    database_url: str,
    *arguments: str,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["alembic", *arguments],
        cwd=BACKEND_ROOT,
        env={**os.environ, "GSP_DATABASE_URL": database_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_durable_billing_migration_preserves_legacy_purchase_data() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_billing_migration_{uuid.uuid4().hex[:12]}"
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
    payment_intent_only_purchase_id = uuid.uuid4().hex
    refunded_purchase_id = uuid.uuid4().hex
    disputed_purchase_id = uuid.uuid4().hex
    direct_fulfilled_purchase_id = uuid.uuid4().hex
    direct_payment_intent_purchase_id = uuid.uuid4().hex
    direct_paid_insert_purchase_id = uuid.uuid4().hex
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
                    "Migration",
                    "x",
                    "now",
                ),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
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
                        %s, %s, 'stripe', %s, %s, %s, 'eur',
                        %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, NULL, %s, %s
                    )
                    """,
                    [
                        (
                            purchase_id,
                            user_id,
                            "starter",
                            100,
                            100,
                            f"legacy-{purchase_id}",
                            f"cs_{purchase_id}",
                            f"pi_{purchase_id}",
                            f"gsubs_credits_{purchase_id[:8]}",
                            "paid",
                            REFERENCE_AT,
                            0,
                            False,
                            0,
                            0,
                            Jsonb(
                                {
                                    "catalog_version": "legacy",
                                    "package_key": "starter",
                                }
                            ),
                            REFERENCE_AT,
                            REFERENCE_AT,
                        ),
                        (
                            refunded_purchase_id,
                            user_id,
                            "growth",
                            350,
                            300,
                            f"legacy-{refunded_purchase_id}",
                            f"cs_{refunded_purchase_id}",
                            f"pi_{refunded_purchase_id}",
                            f"gsubs_credits_{refunded_purchase_id[:8]}",
                            "partially_refunded",
                            REFERENCE_AT,
                            100,
                            False,
                            117,
                            17,
                            Jsonb(
                                {
                                    "catalog_version": "legacy",
                                    "package_key": "growth",
                                }
                            ),
                            REFERENCE_AT,
                            REFERENCE_AT,
                        ),
                        (
                            payment_intent_only_purchase_id,
                            user_id,
                            "starter",
                            100,
                            100,
                            f"legacy-{payment_intent_only_purchase_id}",
                            f"cs_{payment_intent_only_purchase_id}",
                            f"pi_{payment_intent_only_purchase_id}",
                            (f"gsubs_credits_{payment_intent_only_purchase_id[:8]}"),
                            "awaiting_payment",
                            None,
                            0,
                            False,
                            0,
                            0,
                            Jsonb(
                                {
                                    "catalog_version": "legacy",
                                    "package_key": "starter",
                                }
                            ),
                            REFERENCE_AT,
                            REFERENCE_AT,
                        ),
                        (
                            disputed_purchase_id,
                            user_id,
                            "scale",
                            1200,
                            1000,
                            f"legacy-{disputed_purchase_id}",
                            f"cs_{disputed_purchase_id}",
                            f"pi_{disputed_purchase_id}",
                            f"gsubs_credits_{disputed_purchase_id[:8]}",
                            "disputed",
                            REFERENCE_AT,
                            100,
                            True,
                            1200,
                            200,
                            Jsonb(
                                {
                                    "catalog_version": "legacy",
                                    "package_key": "scale",
                                }
                            ),
                            REFERENCE_AT,
                            REFERENCE_AT,
                        ),
                    ],
                )
            connection.commit()

        after = _run_alembic(database_url, "upgrade", "head")
        assert after.returncode == 0, after.stderr

        with psycopg.connect(
            dbname=database_name,
            user=configured_url.username,
            password=configured_url.password,
            host=configured_url.host,
            port=configured_url.port,
        ) as connection:
            # REGRESSION: database-side writes must not leave a checkout on its
            # 24-hour unpaid retention after it becomes a durable payment
            # record. This intentionally bypasses the application service.
            with connection.cursor() as cursor:
                cursor.executemany(
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
                    [
                        (
                            direct_fulfilled_purchase_id,
                            user_id,
                            f"direct-{direct_fulfilled_purchase_id}",
                            f"cs_{direct_fulfilled_purchase_id}",
                            f"gsubs_credits_{direct_fulfilled_purchase_id[:8]}",
                            Jsonb(
                                {
                                    "catalog_version": "direct-trigger-test",
                                    "package_key": "starter",
                                }
                            ),
                            REFERENCE_AT,
                            REFERENCE_AT,
                        ),
                        (
                            direct_payment_intent_purchase_id,
                            user_id,
                            f"direct-{direct_payment_intent_purchase_id}",
                            f"cs_{direct_payment_intent_purchase_id}",
                            (f"gsubs_credits_{direct_payment_intent_purchase_id[:8]}"),
                            Jsonb(
                                {
                                    "catalog_version": "direct-trigger-test",
                                    "package_key": "starter",
                                }
                            ),
                            REFERENCE_AT,
                            REFERENCE_AT,
                        ),
                    ],
                )
            connection.commit()

            initial_retentions = connection.execute(
                """
                SELECT id, financial_retention_until
                FROM credit_purchases
                WHERE id IN (%s, %s)
                """,
                (
                    direct_fulfilled_purchase_id,
                    direct_payment_intent_purchase_id,
                ),
            ).fetchall()
            assert {row[0]: row[1] for row in initial_retentions} == {
                direct_fulfilled_purchase_id: REFERENCE_AT + 86_400,
                direct_payment_intent_purchase_id: REFERENCE_AT + 86_400,
            }

            connection.execute(
                """
                UPDATE credit_purchases
                SET status = 'paid',
                    fulfilled_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    DIRECT_PAYMENT_AT,
                    DIRECT_PAYMENT_AT,
                    direct_fulfilled_purchase_id,
                ),
            )
            connection.execute(
                """
                UPDATE credit_purchases
                SET payment_intent_id = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    f"pi_{direct_payment_intent_purchase_id}",
                    DIRECT_PAYMENT_AT,
                    direct_payment_intent_purchase_id,
                ),
            )
            connection.commit()

            statutory_deadline = financial_retention_deadline(DIRECT_PAYMENT_AT)
            transitioned_retentions = connection.execute(
                """
                SELECT id, financial_retention_until
                FROM credit_purchases
                WHERE id IN (%s, %s)
                """,
                (
                    direct_fulfilled_purchase_id,
                    direct_payment_intent_purchase_id,
                ),
            ).fetchall()
            assert {row[0]: row[1] for row in transitioned_retentions} == {
                direct_fulfilled_purchase_id: statutory_deadline,
                direct_payment_intent_purchase_id: statutory_deadline,
            }

            longer_deadline = statutory_deadline + 86_400
            connection.execute(
                """
                UPDATE credit_purchases
                SET financial_retention_until = %s
                WHERE id = %s
                """,
                (longer_deadline, direct_fulfilled_purchase_id),
            )
            connection.execute(
                """
                UPDATE credit_purchases
                SET payment_intent_id = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    f"pi_{direct_fulfilled_purchase_id}",
                    DIRECT_PAYMENT_AT + 60,
                    direct_fulfilled_purchase_id,
                ),
            )
            connection.commit()
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM credit_purchases
                WHERE id = %s
                """,
                (direct_fulfilled_purchase_id,),
            ).fetchone() == (longer_deadline,)

            # INSERT is covered too: a caller-supplied short value cannot
            # bypass the statutory minimum for an already-paid row.
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
                    updated_at,
                    financial_retention_until
                )
                VALUES (
                    %s, %s, 'stripe', 'starter', 100, 100, 'eur',
                    %s, %s, NULL, %s, %s, 'paid', %s,
                    0, FALSE, 0, 0, %s, NULL, %s, %s, %s
                )
                """,
                (
                    direct_paid_insert_purchase_id,
                    user_id,
                    f"direct-{direct_paid_insert_purchase_id}",
                    f"cs_{direct_paid_insert_purchase_id}",
                    f"pi_{direct_paid_insert_purchase_id}",
                    f"gsubs_credits_{direct_paid_insert_purchase_id[:8]}",
                    DIRECT_PAYMENT_AT,
                    Jsonb(
                        {
                            "catalog_version": "direct-trigger-test",
                            "package_key": "starter",
                        }
                    ),
                    DIRECT_PAYMENT_AT,
                    DIRECT_PAYMENT_AT,
                    DIRECT_PAYMENT_AT + 86_400,
                ),
            )
            connection.commit()
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM credit_purchases
                WHERE id = %s
                """,
                (direct_paid_insert_purchase_id,),
            ).fetchone() == (statutory_deadline,)

            migrated = connection.execute(
                """
                SELECT
                    user_id,
                    package_key,
                    snapshot,
                    account_reference_hash,
                    reversed_amount_cents,
                    payment_snapshot,
                    customer_snapshot,
                    tax_snapshot,
                    financial_retention_until
                FROM credit_purchases
                WHERE id = %s
                """,
                (purchase_id,),
            ).fetchone()
            assert migrated is not None
            assert migrated[0] == user_id
            assert migrated[1] == "starter"
            assert migrated[2]["catalog_version"] == "legacy"
            assert migrated[3] == financial_account_reference_hash(user_id)
            assert migrated[4] == 0
            assert migrated[5:8] == (None, None, None)
            assert migrated[8] == financial_retention_deadline(REFERENCE_AT)

            migrated_reversals = connection.execute(
                """
                SELECT
                    id,
                    refunded_amount_cents,
                    dispute_active,
                    reversed_credits,
                    reversal_debt_credits,
                    reversed_amount_cents,
                    payment_snapshot,
                    customer_snapshot,
                    tax_snapshot
                FROM credit_purchases
                WHERE id IN (%s, %s)
                """,
                (refunded_purchase_id, disputed_purchase_id),
            ).fetchall()
            reversals_by_purchase = {row[0]: row for row in migrated_reversals}
            assert reversals_by_purchase[refunded_purchase_id][1:] == (
                100,
                False,
                117,
                17,
                100,
                None,
                None,
                None,
            )
            assert reversals_by_purchase[disputed_purchase_id][1:] == (
                100,
                True,
                1200,
                200,
                1000,
                None,
                None,
                None,
            )

            invoices = connection.execute(
                """
                SELECT
                    id,
                    purchase_id,
                    document_status,
                    aade_document_type,
                    aade_series,
                    aade_aa,
                    aade_mark,
                    issued_at,
                    recorded_by_user_id,
                    recorded_at,
                    document_snapshot
                FROM billing_invoices
                WHERE purchase_id IN (%s, %s, %s, %s)
                """,
                (
                    purchase_id,
                    payment_intent_only_purchase_id,
                    refunded_purchase_id,
                    disputed_purchase_id,
                ),
            ).fetchall()
            assert len(invoices) == 4
            invoices_by_purchase = {row[1]: row for row in invoices}
            for legacy_purchase_id in (
                purchase_id,
                payment_intent_only_purchase_id,
                refunded_purchase_id,
                disputed_purchase_id,
            ):
                invoice = invoices_by_purchase[legacy_purchase_id]
                assert (
                    invoice[0]
                    == hashlib.md5((f"gsubs-legacy-aade-invoice:v1:{legacy_purchase_id}").encode()).hexdigest()
                )
                assert invoice[2] == "manual_review_required"
                assert invoice[3:10] == (
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                assert invoice[10]["record_origin"] == ("legacy_pre_0013_purchase")
                assert invoice[10]["legacy_incomplete"] is True
                assert invoice[10]["manual_review_required"] is True
                assert invoice[10]["missing_evidence"] == [
                    "payment_snapshot",
                    "customer_snapshot",
                    "tax_snapshot",
                    "aade_document_identity",
                ]
                assert "net_amount_cents" not in invoice[10]
                assert "vat_amount_cents" not in invoice[10]
                assert "customer" not in invoice[10]

            baselines = connection.execute(
                """
                SELECT
                    purchase_id,
                    provider,
                    provider_reversal_id,
                    provider_event_id,
                    kind,
                    amount_cents,
                    status,
                    active
                FROM credit_purchase_reversals
                ORDER BY purchase_id, kind
                """
            ).fetchall()
            assert len(baselines) == 3
            baselines_by_purchase: dict[str, list[tuple[object, ...]]] = {}
            for baseline in baselines:
                baselines_by_purchase.setdefault(
                    str(baseline[0]),
                    [],
                ).append(baseline)
                assert baseline[1] == "legacy_migration"
                assert baseline[2].startswith("legacy:0013:")
                assert baseline[3] is None
                assert baseline[7] is True

            refunded_baseline = baselines_by_purchase[refunded_purchase_id]
            assert [(row[4], row[5], row[6]) for row in refunded_baseline] == [
                ("refund", 100, "legacy_refund_manual_review"),
            ]
            disputed_baselines = baselines_by_purchase[disputed_purchase_id]
            assert [(row[4], row[5], row[6]) for row in disputed_baselines] == [
                ("dispute", 1000, "legacy_dispute_manual_review"),
                ("refund", 100, "legacy_refund_manual_review"),
            ]

        # REGRESSION: a rollback must refuse even while the paid record still
        # belongs to an active user. The former guard only noticed user_id=NULL
        # after it had already issued destructive DROP TABLE statements.
        linked_downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0012_google_avatar_url",
        )
        assert linked_downgrade.returncode != 0
        assert "durable paid financial records exist" in linked_downgrade.stderr

        with psycopg.connect(
            dbname=database_name,
            user=configured_url.username,
            password=configured_url.password,
            host=configured_url.host,
            port=configured_url.port,
        ) as connection:
            # The safety preflight must run before any destructive DDL. All
            # 0013 objects and the paid row must still be present after refusal.
            assert connection.execute("SELECT to_regclass('public.billing_invoices')").fetchone() == (
                "billing_invoices",
            )
            assert connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'credit_purchases'
                  AND column_name = 'payment_snapshot'
                """
            ).fetchone() == ("payment_snapshot",)
            assert connection.execute(
                """
                SELECT column_name, is_nullable, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'billing_invoices'
                  AND column_name IN (
                      'recorded_by_user_id',
                      'recorded_at'
                  )
                ORDER BY column_name
                """
            ).fetchall() == [
                ("recorded_at", "YES", "bigint"),
                ("recorded_by_user_id", "YES", "character varying"),
            ]
            assert connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.key_column_usage AS usage
                JOIN information_schema.table_constraints AS constraint_info
                  ON constraint_info.constraint_catalog = usage.constraint_catalog
                 AND constraint_info.constraint_schema = usage.constraint_schema
                 AND constraint_info.constraint_name = usage.constraint_name
                WHERE usage.table_schema = 'public'
                  AND usage.table_name = 'billing_invoices'
                  AND usage.column_name = 'recorded_by_user_id'
                  AND constraint_info.constraint_type = 'FOREIGN KEY'
                """
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT fulfilled_at FROM credit_purchases WHERE id = %s",
                (purchase_id,),
            ).fetchone() == (REFERENCE_AT,)

            # REGRESSION: the former ON DELETE CASCADE removed every payment
            # record when its user account was deleted.
            connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
            anonymized_user_id = connection.execute(
                "SELECT user_id FROM credit_purchases WHERE id = %s",
                (purchase_id,),
            ).fetchone()
            assert anonymized_user_id == (None,)
            connection.commit()

        downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0012_google_avatar_url",
        )
        assert downgrade.returncode != 0
        assert "anonymized credit purchases exist" in downgrade.stderr
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
