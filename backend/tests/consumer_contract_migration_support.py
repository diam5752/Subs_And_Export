from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

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
