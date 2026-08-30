from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)
from backend.tests.billing_financial_migration_support import (
    DIRECT_PAYMENT_AT,
    REFERENCE_AT,
    _assert_legacy_financial_records,
    _run_alembic,
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

            _assert_legacy_financial_records(
                connection,
                purchase_id=purchase_id,
                payment_intent_only_purchase_id=payment_intent_only_purchase_id,
                refunded_purchase_id=refunded_purchase_id,
                disputed_purchase_id=disputed_purchase_id,
            )

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
