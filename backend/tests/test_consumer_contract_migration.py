from __future__ import annotations

import hashlib
import os
import time
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from backend.tests.consumer_contract_migration_support import (
    AVAILABLE_AT,
    CONCLUDED_AT,
    RETAIN_UNTIL,
    _insert_confirmation,
    _insert_purchase,
    _insert_withdrawal,
    _run_alembic,
)


def test_consumer_contract_migration_is_append_only_and_downgrade_safe() -> None:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_consumer_migration_{uuid.uuid4().hex[:12]}"
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
    user_id = uuid.uuid4().hex
    purchase_id = uuid.uuid4().hex
    second_purchase_id = uuid.uuid4().hex
    confirmation_id = uuid.uuid4().hex
    expirable_confirmation_id = uuid.uuid4().hex
    withdrawal_id = uuid.uuid4().hex
    spoof_guard_invoice_id = uuid.uuid4().hex
    connection_parameters = {
        "dbname": database_name,
        "user": configured_url.username,
        "password": configured_url.password,
        "host": configured_url.host,
        "port": configured_url.port,
    }
    try:
        before = _run_alembic(
            database_url,
            "upgrade",
            "0013_durable_billing_records",
        )
        assert before.returncode == 0, before.stderr
        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        clean_downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0013_durable_billing_records",
        )
        assert clean_downgrade.returncode == 0, clean_downgrade.stderr
        reupgrade = _run_alembic(database_url, "upgrade", "head")
        assert reupgrade.returncode == 0, reupgrade.stderr

        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.billing_contract_confirmations')",
            ).fetchone() == ("billing_contract_confirmations",)
            assert connection.execute(
                "SELECT to_regclass('public.billing_withdrawal_requests')",
            ).fetchone() == ("billing_withdrawal_requests",)
            protected_functions = {
                "gsubs_financial_retention_deadline",
                "gsubs_prepare_credit_purchase_financial_record",
                "gsubs_enforce_credit_purchase_immutability",
                "gsubs_prepare_billing_invoice",
                "gsubs_enforce_billing_invoice_immutability",
                "gsubs_enforce_credit_purchase_reversal_timestamps",
                "gsubs_reject_durable_billing_truncate",
                "gsubs_guard_durable_billing_delete",
                "gsubs_prepare_contract_confirmation_retention",
                "gsubs_prepare_withdrawal_request_retention",
                "gsubs_reject_append_only_billing_mutation",
            }
            function_configs = {
                row[0]: row[1]
                for row in connection.execute(
                    """
                    SELECT procedure.proname, procedure.proconfig
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname = ANY(%s)
                    """,
                    (list(protected_functions),),
                ).fetchall()
            }
            assert set(function_configs) == protected_functions
            assert all(config == ["search_path=pg_catalog, public"] for config in function_configs.values())
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
            _insert_purchase(
                connection,
                purchase_id=purchase_id,
                user_id=user_id,
            )
            _insert_purchase(
                connection,
                purchase_id=second_purchase_id,
                user_id=user_id,
            )
            connection.execute("CREATE SCHEMA retention_spoof")
            connection.execute(
                """
                CREATE FUNCTION
                    retention_spoof.gsubs_financial_retention_deadline(BIGINT)
                RETURNS BIGINT
                LANGUAGE SQL
                IMMUTABLE
                STRICT
                AS 'SELECT 1::BIGINT'
                """
            )
            connection.execute(
                "SET search_path = retention_spoof, public",
            )
            _insert_confirmation(
                connection,
                confirmation_id=confirmation_id,
                purchase_id=purchase_id,
                financial_retention_until=1,
            )
            _insert_withdrawal(
                connection,
                withdrawal_id=withdrawal_id,
                purchase_id=purchase_id,
                financial_retention_until=1,
            )
            connection.execute("RESET search_path")
            # REGRESSION: non-null caller values cannot shorten the statutory
            # retention floor for either immutable consumer record.
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM billing_contract_confirmations
                WHERE id = %s
                """,
                (confirmation_id,),
            ).fetchone() == (RETAIN_UNTIL,)
            assert connection.execute(
                """
                SELECT financial_retention_until
                FROM billing_withdrawal_requests
                WHERE id = %s
                """,
                (withdrawal_id,),
            ).fetchone() == (RETAIN_UNTIL,)
            connection.execute(
                """
                CREATE TABLE retention_spoof.billing_contract_confirmations (
                    purchase_id TEXT,
                    financial_retention_until BIGINT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE retention_spoof.billing_withdrawal_requests (
                    purchase_id TEXT,
                    status TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO public.billing_invoices (
                    id, purchase_id, provider, document_kind,
                    document_status, document_snapshot,
                    financial_retention_until, created_at, updated_at
                )
                VALUES (
                    %s, %s, 'aade_etimologio',
                    'retail_service_receipt', 'manual_review_required',
                    %s, 1, %s, %s
                )
                """,
                (
                    spoof_guard_invoice_id,
                    purchase_id,
                    Jsonb({"service_code": "4"}),
                    CONCLUDED_AT,
                    CONCLUDED_AT,
                ),
            )
            # REGRESSION: a caller-controlled search_path must not redirect the
            # retention guard from the real pending-withdrawal hold to attacker-
            # or accidentally-created empty lookalike tables.
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="retained financial evidence",
            ):
                with connection.transaction():
                    connection.execute(
                        "SET LOCAL search_path = retention_spoof, public",
                    )
                    connection.execute(
                        """
                        SELECT set_config(
                            'gsubs.billing_retention_cutoff',
                            %s,
                            true
                        )
                        """,
                        (str(RETAIN_UNTIL),),
                    )
                    connection.execute(
                        """
                        DELETE FROM public.billing_invoices
                        WHERE id = %s
                        """,
                        (spoof_guard_invoice_id,),
                    )

            with pytest.raises(psycopg.errors.UniqueViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=purchase_id,
                )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=uuid.uuid4().hex,
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    locale="fr",
                )
            # The reviewed migration remains fail-closed for unknown delivery
            # identities.
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    delivery_status="available_unknown",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    content_sha256="g" * 64,
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    content_sha256="a" * 64,
                )
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="chk_billing_contract_confirmations_identity",
            ):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    content_bytes=b'{"corrupt":true}\n',
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    content_bytes=b'{"changed":true}\n',
                    content_sha256=hashlib.sha256(b"{}\n").hexdigest(),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    content_bytes=b"",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    mime_type="text/plain",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    filename="wrong.json",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_confirmation(
                    connection,
                    confirmation_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    created_at=AVAILABLE_AT + 1,
                )
            with pytest.raises(psycopg.errors.UniqueViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=purchase_id,
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    status="resolved",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    request_sha256="G" * 64,
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    request_sha256="a" * 64,
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    acknowledgement_sha256="a" * 64,
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    acknowledgement_bytes=b"",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    acknowledgement_mime_type="text/plain",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    acknowledgement_filename="wrong.json",
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    created_at=AVAILABLE_AT + 1,
                )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                )

            _insert_confirmation(
                connection,
                confirmation_id=expirable_confirmation_id,
                purchase_id=second_purchase_id,
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    request_bytes=b'{"purchase_id":"different"}\n',
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_withdrawal(
                    connection,
                    withdrawal_id=uuid.uuid4().hex,
                    purchase_id=second_purchase_id,
                    request_bytes=b"null\n",
                    request_snapshot_is_json_null=True,
                )

            for table_name, record_id in (
                ("billing_contract_confirmations", confirmation_id),
                ("billing_withdrawal_requests", withdrawal_id),
            ):
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="append-only",
                ):
                    connection.execute(
                        sql.SQL("UPDATE {} SET created_at = created_at + 1 WHERE id = %s").format(
                            sql.Identifier(table_name)
                        ),
                        (record_id,),
                    )
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="append-only",
                ):
                    connection.execute(
                        sql.SQL("TRUNCATE TABLE {} CASCADE").format(
                            sql.Identifier(table_name),
                        )
                    )
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="append-only",
                ):
                    connection.execute(
                        sql.SQL("DELETE FROM {} WHERE id = %s").format(
                            sql.Identifier(table_name),
                        ),
                        (record_id,),
                    )
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="append-only",
                ):
                    with connection.transaction():
                        connection.execute(
                            "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                            (str(RETAIN_UNTIL - 1),),
                        )
                        connection.execute(
                            sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table_name)),
                            (record_id,),
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
                        "DELETE FROM billing_contract_confirmations WHERE id = %s",
                        (confirmation_id,),
                    )

            # A pending withdrawal is an unresolved compliance hold and must
            # remain append-only even after its nominal retention date.
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="append-only",
            ):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(RETAIN_UNTIL),),
                    )
                    connection.execute(
                        "DELETE FROM billing_withdrawal_requests WHERE id = %s",
                        (withdrawal_id,),
                    )

            # The confirmation is parent evidence for the pending withdrawal
            # and must not disappear even after retention expires.
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                        (str(RETAIN_UNTIL),),
                    )
                    connection.execute(
                        "DELETE FROM billing_contract_confirmations WHERE id = %s",
                        (confirmation_id,),
                    )

            # Expired confirmation artifacts can be removed only through the
            # bounded retention path, when no withdrawal depends on them.
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('gsubs.billing_retention_cutoff', %s, true)",
                    (str(RETAIN_UNTIL),),
                )
                connection.execute(
                    "DELETE FROM billing_contract_confirmations WHERE id = %s",
                    (expirable_confirmation_id,),
                )
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_contract_confirmations",
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_withdrawal_requests",
            ).fetchone() == (1,)

            # The launch-preparation migration permits the exact approved
            # account-vault identity while preserving legacy pending evidence.
            approved_confirmation_id = uuid.uuid4().hex
            _insert_confirmation(
                connection,
                confirmation_id=approved_confirmation_id,
                purchase_id=second_purchase_id,
                delivery_status="available_approved",
            )
            assert connection.execute(
                """
                SELECT delivery_channel, delivery_status
                FROM billing_contract_confirmations
                WHERE id = %s
                """,
                (approved_confirmation_id,),
            ).fetchone() == (
                "account_vault",
                "available_approved",
            )

        refused = _run_alembic(
            database_url,
            "downgrade",
            "0013_durable_billing_records",
        )
        assert refused.returncode != 0
        assert (
            "Cannot downgrade approved contract-confirmation delivery while approved durable evidence exists."
        ) in refused.stderr
        current = _run_alembic(database_url, "current")
        assert current.returncode == 0, current.stderr
        assert "0027_restore_beta_promo_cap (head)" in current.stdout
        with psycopg.connect(
            **connection_parameters,
            autocommit=True,
        ) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_contract_confirmations",
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT COUNT(*) FROM billing_withdrawal_requests",
            ).fetchone() == (1,)
            constraint_definition = connection.execute(
                """
                SELECT pg_get_constraintdef(constraint_oid.oid)
                FROM pg_constraint AS constraint_oid
                JOIN pg_class AS table_oid
                  ON table_oid.oid = constraint_oid.conrelid
                JOIN pg_namespace AS namespace_oid
                  ON namespace_oid.oid = table_oid.relnamespace
                WHERE namespace_oid.nspname = 'public'
                  AND table_oid.relname = 'billing_contract_confirmations'
                  AND constraint_oid.conname =
                    'chk_billing_contract_confirmations_delivery'
                """
            ).fetchone()
            assert constraint_definition is not None
            assert "available_approved" in str(
                constraint_definition[0],
            )
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
