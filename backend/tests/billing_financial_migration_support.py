from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

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


def _assert_legacy_financial_records(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    purchase_id: str,
    payment_intent_only_purchase_id: str,
    refunded_purchase_id: str,
    disputed_purchase_id: str,
) -> None:
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
        assert invoice[0] == hashlib.md5(f"gsubs-legacy-aade-invoice:v1:{legacy_purchase_id}".encode()).hexdigest()
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
        assert invoice[10]["record_origin"] == "legacy_pre_0013_purchase"
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
