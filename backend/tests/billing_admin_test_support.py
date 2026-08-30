from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbUser,
)
from backend.app.services.billing import CATALOG_VERSION
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordStore,
    new_contract_confirmation,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    build_consumer_contract_snapshot,
    consumer_contract_snapshot_sha256,
    public_consumer_contract,
)
from backend.app.services.financial_records import financial_retention_deadline


def _auth_headers(
    client: TestClient,
    *,
    email: str,
    verified: bool = True,
) -> tuple[dict[str, str], str]:
    register = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "testpassword123",
            "name": "Billing Admin Test",
        },
    )
    assert register.status_code == 200
    if verified:
        db = Database()
        with db.session() as session:
            user = session.get(DbUser, register.json()["id"])
            assert user is not None
            user.email_verified = True
    token = client.post(
        "/auth/token",
        data={"username": email, "password": "testpassword123"},
    )
    assert token.status_code == 200
    return (
        {"Authorization": f"Bearer {token.json()['access_token']}"},
        register.json()["id"],
    )


def _seed_pending_invoice(
    *,
    user_id: str,
    payment_confirmation_at: int | None = None,
    legacy_missing_payment_snapshot: bool = False,
    purchase_fulfilled: bool = True,
    consumer_contract_snapshot: dict[str, Any] | None = None,
) -> tuple[str, str, int]:
    suffix = uuid.uuid4().hex
    purchase_id = suffix[:32]
    invoice_id = uuid.uuid4().hex
    created_at = 1_600_000_000
    retention_until = financial_retention_deadline(created_at)
    purchase_snapshot = (
        {
            "package_key": "starter",
            "credits": 100,
            "amount_eur_cents": 100,
            "currency": "eur",
            "consumer_contract": {
                "confirmed_name": "Must not reach the admin browser",
            },
        }
        if consumer_contract_snapshot is None
        else {
            "catalog_version": CATALOG_VERSION,
            "package_key": "starter",
            "credits": 100,
            "amount_eur_cents": 100,
            "currency": "eur",
            "stripe_price_id": "price_test_starter",
            "billing_country": "GR",
            "consumer_contract": consumer_contract_snapshot,
            "consumer_contract_sha256": (
                consumer_contract_snapshot_sha256(
                    consumer_contract_snapshot,
                )
            ),
        }
    )
    purchase = DbCreditPurchase(
        id=purchase_id,
        user_id=user_id,
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"admin-aade-{suffix}",
        checkout_session_id=f"cs_test_{suffix}",
        checkout_url=None,
        payment_intent_id=f"pi_{suffix}",
        integration_identifier="gsubs_credits_v1",
        status="paid",
        fulfilled_at=created_at if purchase_fulfilled else None,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot=purchase_snapshot,
        payment_snapshot=(
            None
            if legacy_missing_payment_snapshot
            else {
                "checkout_session_id": f"cs_test_{suffix}",
                "payment_intent_id": f"pi_{suffix}",
                "stripe_customer_id": f"cus_{suffix}",
                "stripe_event_created": (created_at if payment_confirmation_at is None else payment_confirmation_at),
                "livemode": False,
                "amount_paid_cents": 100,
                "currency": "eur",
                "payment_status": "paid",
            }
        ),
        customer_snapshot={
            "name": "AADE Customer",
            "email": f"{suffix}@example.com",
            "country": "GR",
            "city": "Athens",
            "postal_code": "10558",
            "line1": "1 Ermou Street",
            "line2": "Floor 2",
            "state": "Attica",
            "status": "ready_for_manual_issue",
            "missing_required_fields": [],
        },
        tax_snapshot={
            "tax_behavior": "inclusive",
            "tax_ids": [{"type": "eu_vat", "value": "EL000000000"}],
            "vat_rate_percent": 24,
            "gross_amount_cents": 100,
            "net_amount_cents": 81,
            "vat_amount_cents": 19,
        },
        financial_retention_until=retention_until,
        error=None,
        created_at=created_at,
        updated_at=created_at,
    )
    invoice = DbBillingInvoice(
        id=invoice_id,
        purchase_id=purchase_id,
        provider="aade_etimologio",
        document_kind="retail_service_receipt",
        document_status=("manual_review_required" if legacy_missing_payment_snapshot else "pending_manual_issue"),
        aade_document_type=None,
        aade_series=None,
        aade_aa=None,
        aade_mark=None,
        issued_at=None,
        recorded_by_user_id=None,
        recorded_at=None,
        document_snapshot=(
            {
                "migration_source": "0013_durable_billing_records",
                "legacy_incomplete": True,
                "service_code": "4",
                "service_name": "GSUBS Credits",
                "gross_amount_cents": 100,
            }
            if legacy_missing_payment_snapshot
            else {
                "service_code": "4",
                "service_name": "GSUBS Credits",
                "gross_amount_cents": 100,
            }
        ),
        financial_retention_until=retention_until,
        created_at=created_at,
        updated_at=created_at,
    )
    db = Database()
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)
    return purchase_id, invoice_id, retention_until


def _set_purchase_reversal_state(
    *,
    purchase_id: str,
    status: str,
    refunded_amount_cents: int = 0,
    reversed_amount_cents: int = 0,
    reversed_credits: int = 0,
    dispute_active: bool = False,
) -> None:
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        purchase.status = status
        purchase.refunded_amount_cents = refunded_amount_cents
        purchase.reversed_amount_cents = reversed_amount_cents
        purchase.reversed_credits = reversed_credits
        purchase.dispute_active = dispute_active
        purchase.updated_at += 1


def _issued_payload(*, issued_at: int) -> dict[str, str | int]:
    return {
        "document_type": "11.2",
        "series": "0",
        "aa": str(uuid.uuid4().int % 10**18),
        "mark": f"4{uuid.uuid4().int % 10**15:015d}",
        "issued_at": issued_at,
    }


def _adjustment_payload(*, issued_at: int) -> dict[str, str | int]:
    return {
        "document_type": "11.4",
        "series": f"RET-{uuid.uuid4().hex[:8]}",
        "aa": str(uuid.uuid4().int % 10**18),
        "mark": f"5{uuid.uuid4().int % 10**15:015d}",
        "issued_at": issued_at,
    }


def _canonical_consumer_contract_snapshot(
    *,
    accepted_at: int,
) -> dict[str, Any]:
    disclosure = public_consumer_contract("el")
    acceptance = ConsumerContractAcceptance(
        catalog_version=CATALOG_VERSION,
        disclosure_id=str(disclosure["disclosure_id"]),
        disclosure_sha256=str(disclosure["disclosure_sha256"]),
        locale="el",
        policy_version=str(disclosure["policy_version"]),
        terms_version=str(disclosure["terms_version"]),
        withdrawal_notice_version=str(
            disclosure["withdrawal_notice_version"],
        ),
        terms_accepted=True,
        immediate_performance_requested=True,
        withdrawal_consequences_acknowledged=True,
    )
    return build_consumer_contract_snapshot(
        acceptance,
        expected_catalog_version=CATALOG_VERSION,
        accepted_at=accepted_at,
    )


def _seed_completed_stripe_refund(
    *,
    purchase_id: str,
    provider_event_created: int,
    status: str = "succeeded",
    active: bool = True,
    amount_cents: int = 100,
) -> tuple[str, str]:
    reversal_id = uuid.uuid4().hex
    stripe_refund_id = f"re_{uuid.uuid4().hex}"
    now = max(provider_event_created, 1)
    reversal = DbCreditPurchaseReversal(
        id=reversal_id,
        purchase_id=purchase_id,
        provider="stripe",
        provider_reversal_id=stripe_refund_id,
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=provider_event_created,
        kind="refund",
        amount_cents=amount_cents,
        currency="eur",
        status=status,
        active=active,
        created_at=now,
        updated_at=now,
    )
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        session.add(reversal)
        if status == "succeeded" and active:
            purchase.status = "refunded" if amount_cents == purchase.amount_eur_cents else "partially_refunded"
            purchase.refunded_amount_cents = amount_cents
            purchase.reversed_amount_cents = amount_cents
            purchase.updated_at = max(purchase.updated_at, now)
    return reversal_id, stripe_refund_id


def _seed_contract_and_withdrawal(
    *,
    purchase_id: str,
    user_id: str,
    email: str,
    submitted_at: int,
) -> str:
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        confirmation = new_contract_confirmation(
            purchase=purchase,
            contract_concluded_at=submitted_at - 2,
            generated_at=submitted_at - 1,
        )
        session.add(confirmation)
    result = BillingConsumerRecordStore(db=db).submit_withdrawal(
        user_id=user_id,
        purchase_id=purchase_id,
        idempotency_key=f"withdrawal-{uuid.uuid4().hex}",
        locale="el",
        withdrawal_requested=True,
        confirmed_name="Billing Admin Test",
        confirmation_email=email,
        submitted_at=submitted_at,
    )
    return result.withdrawal_id


def _manual_refund_accounting_payload(
    *,
    payment_at: int,
    refund_at: int,
) -> dict[str, Any]:
    return {
        "original_document": _issued_payload(
            issued_at=max(payment_at, refund_at - 2),
        ),
        "adjustment_document": _adjustment_payload(
            issued_at=refund_at + 1,
        ),
        "final_manual_actions_confirmed": True,
    }


def _assert_sensitive_admin_response_is_not_cacheable(
    response: Any,
) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def _allow_billing_admin(
    monkeypatch: pytest.MonkeyPatch,
    user_id: str,
) -> None:
    monkeypatch.setenv(
        "GSP_BILLING_ADMIN_USER_IDS",
        f" {uuid.uuid4().hex}, {user_id} ",
    )


def _find_pending_invoice(
    client: TestClient,
    *,
    headers: dict[str, str],
    invoice_id: str,
) -> dict[str, Any]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params = {"limit": "100"}
        if cursor is not None:
            params["after"] = cursor
        response = client.get(
            "/billing/admin/invoices/pending",
            headers=headers,
            params=params,
        )
        assert response.status_code == 200, response.json()
        payload = cast(dict[str, Any], response.json())
        items = cast(list[dict[str, Any]], payload["items"])
        for item in items:
            if item["invoice_id"] == invoice_id:
                return item
        cursor = payload["next_cursor"]
        assert cursor is not None, f"Pending invoice {invoice_id} was not listed"
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)


def _all_pending_invoice_ids(
    client: TestClient,
    *,
    headers: dict[str, str],
) -> set[str]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    invoice_ids: set[str] = set()
    while True:
        params = {"limit": "100"}
        if cursor is not None:
            params["after"] = cursor
        response = client.get(
            "/billing/admin/invoices/pending",
            headers=headers,
            params=params,
        )
        assert response.status_code == 200
        payload = cast(dict[str, Any], response.json())
        items = cast(list[dict[str, Any]], payload["items"])
        invoice_ids.update(cast(str, item["invoice_id"]) for item in items)
        cursor = cast(str | None, payload["next_cursor"])
        if cursor is None:
            return invoice_ids
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)


def _find_pending_review(
    client: TestClient,
    *,
    headers: dict[str, str],
    resource: str,
    identity_key: str,
    identity_value: str,
) -> dict[str, Any]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params = {"limit": "100"}
        if cursor is not None:
            params["after"] = cursor
        response = client.get(
            f"/billing/admin/{resource}/pending",
            headers=headers,
            params=params,
        )
        assert response.status_code == 200, response.json()
        payload = cast(dict[str, Any], response.json())
        items = cast(list[dict[str, Any]], payload["items"])
        for item in items:
            if item[identity_key] == identity_value:
                return item
        cursor = cast(str | None, payload["next_cursor"])
        assert cursor is not None, f"Pending {resource} review {identity_value} was not listed"
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)


def _all_pending_review_ids(
    client: TestClient,
    *,
    headers: dict[str, str],
    resource: str,
    identity_key: str,
) -> set[str]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    review_ids: set[str] = set()
    while True:
        params = {"limit": "100"}
        if cursor is not None:
            params["after"] = cursor
        response = client.get(
            f"/billing/admin/{resource}/pending",
            headers=headers,
            params=params,
        )
        assert response.status_code == 200
        payload = cast(dict[str, Any], response.json())
        items = cast(list[dict[str, Any]], payload["items"])
        review_ids.update(cast(str, item[identity_key]) for item in items)
        cursor = cast(str | None, payload["next_cursor"])
        if cursor is None:
            return review_ids
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)


__all__ = [
    "Any",
    "BillingConsumerRecordStore",
    "CATALOG_VERSION",
    "ConsumerContractAcceptance",
    "DBAPIError",
    "Database",
    "DbBillingAdjustmentRecord",
    "DbBillingContractConfirmation",
    "DbBillingInvoice",
    "DbBillingWithdrawalResolution",
    "DbCreditPurchase",
    "DbCreditPurchaseReversal",
    "DbUser",
    "TestClient",
    "ThreadPoolExecutor",
    "_adjustment_payload",
    "_all_pending_invoice_ids",
    "_all_pending_review_ids",
    "_allow_billing_admin",
    "_assert_sensitive_admin_response_is_not_cacheable",
    "_auth_headers",
    "_canonical_consumer_contract_snapshot",
    "_find_pending_invoice",
    "_find_pending_review",
    "_issued_payload",
    "_manual_refund_accounting_payload",
    "_seed_completed_stripe_refund",
    "_seed_contract_and_withdrawal",
    "_seed_pending_invoice",
    "_set_purchase_reversal_state",
    "build_consumer_contract_snapshot",
    "cast",
    "consumer_contract_snapshot_sha256",
    "financial_retention_deadline",
    "new_contract_confirmation",
    "public_consumer_contract",
    "pytest",
    "select",
    "text",
    "time",
    "uuid",
]
