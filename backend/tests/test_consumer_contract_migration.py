from __future__ import annotations

import hashlib
import json
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

from backend.app.services.financial_records import financial_retention_deadline

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONCLUDED_AT = 1_577_836_800
AVAILABLE_AT = CONCLUDED_AT + 60
RETAIN_UNTIL = financial_retention_deadline(AVAILABLE_AT)


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


def _insert_purchase(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    purchase_id: str,
    user_id: str,
) -> None:
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
            100, 'eur', %s, %s, NULL, NULL,
            %s, 'failed', NULL, 0, FALSE, 0, 0, 0, %s,
            NULL, NULL, NULL, %s, NULL, %s, %s
        )
        """,
        (
            purchase_id,
            user_id,
            f"migration-{purchase_id}",
            f"cs_test_{purchase_id}",
            f"gsubs_credits_{purchase_id[:8]}",
            Jsonb({"catalog_version": "migration-test"}),
            RETAIN_UNTIL,
            CONCLUDED_AT,
            CONCLUDED_AT,
        ),
    )


def _insert_confirmation(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    confirmation_id: str,
    purchase_id: str,
    locale: str = "el",
    delivery_status: str = "available_pending_external_approval",
    content_bytes: bytes | None = None,
    content_sha256: str | None = None,
    mime_type: str = "application/json; charset=utf-8",
    filename: str | None = None,
    created_at: int = AVAILABLE_AT,
    financial_retention_until: int = RETAIN_UNTIL,
) -> None:
    resolved_content_bytes = (
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "document_type": "gsubs_consumer_contract_confirmation",
                    "delivery_channel": "account_vault",
                    "delivery_status": delivery_status,
                    "contract_concluded_at": CONCLUDED_AT,
                    "available_at": AVAILABLE_AT,
                    "purchase": {"purchase_id": purchase_id},
                    "consumer_contract_sha256": "b" * 64,
                    "consumer_contract": {"locale": locale},
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
        if content_bytes is None
        else content_bytes
    )
    resolved_content_sha256 = (
        hashlib.sha256(resolved_content_bytes).hexdigest() if content_sha256 is None else content_sha256
    )
    connection.execute(
        """
        INSERT INTO billing_contract_confirmations (
            id, purchase_id, schema_version, locale,
            contract_concluded_at, mime_type, filename, content_bytes,
            content_sha256, consumer_contract_sha256, delivery_channel,
            delivery_status, available_at, financial_retention_until,
            created_at
        )
        VALUES (
            %s, %s, 1, %s, %s, %s,
            %s, %s, %s, %s, 'account_vault', %s, %s, %s, %s
        )
        """,
        (
            confirmation_id,
            purchase_id,
            locale,
            CONCLUDED_AT,
            mime_type,
            filename or f"gsubs-contract-{purchase_id}.json",
            resolved_content_bytes,
            resolved_content_sha256,
            "b" * 64,
            delivery_status,
            AVAILABLE_AT,
            financial_retention_until,
            created_at,
        ),
    )


def _insert_withdrawal(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    withdrawal_id: str,
    purchase_id: str,
    status: str = "pending_manual_review",
    request_sha256: str | None = None,
    request_bytes: bytes | None = None,
    request_snapshot_is_json_null: bool = False,
    acknowledgement_bytes: bytes = b"{}\n",
    acknowledgement_sha256: str | None = None,
    acknowledgement_mime_type: str = "application/json; charset=utf-8",
    acknowledgement_filename: str | None = None,
    created_at: int = AVAILABLE_AT,
    financial_retention_until: int = RETAIN_UNTIL,
) -> None:
    request_snapshot = None if request_snapshot_is_json_null else {"purchase_id": purchase_id}
    canonical_request_bytes = (
        json.dumps(
            request_snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    resolved_request_bytes = canonical_request_bytes if request_bytes is None else request_bytes
    resolved_request_sha256 = (
        hashlib.sha256(resolved_request_bytes).hexdigest() if request_sha256 is None else request_sha256
    )
    resolved_acknowledgement_sha256 = (
        hashlib.sha256(acknowledgement_bytes).hexdigest() if acknowledgement_sha256 is None else acknowledgement_sha256
    )
    connection.execute(
        """
        INSERT INTO billing_withdrawal_requests (
            id, purchase_id, idempotency_key, schema_version, locale,
            status, request_snapshot, request_bytes, request_sha256, submitted_at,
            acknowledgement_mime_type, acknowledgement_filename,
            acknowledgement_bytes, acknowledgement_sha256, available_at,
            financial_retention_until, created_at
        )
        VALUES (
            %s, %s, %s, 1, 'el', %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            withdrawal_id,
            purchase_id,
            f"withdrawal-{withdrawal_id}",
            status,
            Jsonb(request_snapshot),
            resolved_request_bytes,
            resolved_request_sha256,
            AVAILABLE_AT,
            acknowledgement_mime_type,
            acknowledgement_filename or f"gsubs-withdrawal-{purchase_id}.json",
            acknowledgement_bytes,
            resolved_acknowledgement_sha256,
            AVAILABLE_AT,
            financial_retention_until,
            created_at,
        ),
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
            assert all(
                config == ["search_path=pg_catalog, public"]
                for config in function_configs.values()
            )
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
            "Cannot downgrade approved contract-confirmation delivery "
            "while approved durable evidence exists."
        ) in refused.stderr
        current = _run_alembic(database_url, "current")
        assert current.returncode == 0, current.stderr
        assert "0023_beta_login_promotion (head)" in current.stdout
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
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0017_remove_signup_markers",)
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
            "Cannot downgrade approved contract-confirmation delivery "
            "while approved durable evidence exists."
        ) in stderr
        current = _run_alembic(database_url, "current")
        assert current.returncode == 0, current.stderr
        assert "0023_beta_login_promotion (head)" in current.stdout
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
