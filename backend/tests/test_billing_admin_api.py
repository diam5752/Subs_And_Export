from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.core.database import Database
from backend.app.db.models import DbBillingInvoice, DbCreditPurchase, DbUser
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
) -> tuple[str, str, int]:
    suffix = uuid.uuid4().hex
    purchase_id = suffix[:32]
    invoice_id = uuid.uuid4().hex
    created_at = 1_600_000_000
    retention_until = financial_retention_deadline(created_at)
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
        snapshot={
            "package_key": "starter",
            "credits": 100,
            "amount_eur_cents": 100,
            "currency": "eur",
            "consumer_contract": {
                "confirmed_name": "Must not reach the admin browser",
            },
        },
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
        assert response.status_code == 200
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


def test_pending_invoices_requires_authentication(client: TestClient) -> None:
    response = client.get("/billing/admin/invoices/pending")

    assert response.status_code == 401


def test_record_issued_requires_authentication(client: TestClient) -> None:
    response = client.post(
        f"/billing/admin/invoices/{uuid.uuid4().hex}/record-issued",
        json=_issued_payload(issued_at=int(time.time()) - 30),
    )

    assert response.status_code == 401


@pytest.mark.parametrize("configured", (None, "", "   "))
def test_pending_invoices_fails_closed_without_admin_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
) -> None:
    if configured is None:
        monkeypatch.delenv("GSP_BILLING_ADMIN_USER_IDS", raising=False)
    else:
        monkeypatch.setenv("GSP_BILLING_ADMIN_USER_IDS", configured)
    headers, _ = _auth_headers(
        client,
        email=f"billing-nonadmin-{uuid.uuid4().hex}@example.com",
    )

    response = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access not configured"


@pytest.mark.parametrize(
    "configured_template",
    (
        "billing-admin@example.com",
        "{user_id},not-a-user-id",
        ",{user_id}",
        "{user_id},",
        "{user_id},,{other_user_id}",
        "{user_id},{user_id}",
        "{uppercase_user_id}",
        "0123456789abcde",
        "0" * 65,
    ),
)
def test_pending_invoices_fails_closed_for_invalid_admin_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    configured_template: str,
) -> None:
    headers, user_id = _auth_headers(
        client,
        email=f"billing-admin-{uuid.uuid4().hex}@example.com",
    )
    monkeypatch.setenv(
        "GSP_BILLING_ADMIN_USER_IDS",
        configured_template.format(
            user_id=user_id,
            other_user_id=uuid.uuid4().hex,
            uppercase_user_id=user_id.upper(),
        ),
    )

    response = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ("Admin access configuration is invalid")


def test_pending_invoices_rejects_non_admin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = _auth_headers(
        client,
        email=f"billing-nonadmin-{uuid.uuid4().hex}@example.com",
    )
    monkeypatch.setenv(
        "GSP_BILLING_ADMIN_USER_IDS",
        uuid.uuid4().hex,
    )

    response = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"


def test_pending_invoices_rejects_unverified_allowlisted_account(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email, verified=False)
    _allow_billing_admin(monkeypatch, user_id)

    response = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Verified admin account required"


@pytest.mark.parametrize(
    "session_clock_offset",
    (
        -901,
        3_600,
    ),
    ids=("older-than-fifteen-minutes", "future-dated"),
)
def test_record_issued_requires_a_recent_admin_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_clock_offset: int,
) -> None:
    now = int(time.time())
    with monkeypatch.context() as session_clock:
        session_clock.setattr(
            "backend.app.core.auth.time.time",
            lambda: now + session_clock_offset,
        )
        headers, user_id = _auth_headers(
            client,
            email=f"billing-admin-recent-{uuid.uuid4().hex}@example.com",
        )
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)

    # Reading the queue remains available to the allowlisted verified admin,
    # but the irreversible tax-record mutation needs a fresh sign-in.
    listed = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
    )
    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=now - 30),
    )

    assert listed.status_code == 200
    assert response.status_code == 403
    assert response.json()["detail"] == "Recent sign-in required"
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_mark is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None


def test_re_registered_admin_email_does_not_inherit_user_id_access(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-takeover-{uuid.uuid4().hex}@example.com"
    original_headers, original_user_id = _auth_headers(
        client,
        email=email,
    )
    _allow_billing_admin(monkeypatch, original_user_id)
    original_access = client.get(
        "/billing/admin/invoices/pending",
        headers=original_headers,
    )
    assert original_access.status_code == 200

    deleted = client.delete("/auth/me", headers=original_headers)
    assert deleted.status_code == 200

    replacement_headers, replacement_user_id = _auth_headers(
        client,
        email=email,
    )
    assert replacement_user_id != original_user_id

    replacement_access = client.get(
        "/billing/admin/invoices/pending",
        headers=replacement_headers,
    )

    assert replacement_access.status_code == 403
    assert replacement_access.json()["detail"] == "Not authorized"


def test_admin_lists_only_typed_privacy_minimized_reconciliation_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)

    item = _find_pending_invoice(
        client,
        headers=headers,
        invoice_id=invoice_id,
    )

    assert item["purchase_id"] == purchase_id
    assert item["document_status"] == "pending_manual_issue"
    assert item["purchase_status"] == "paid"
    assert item["refunded_amount_cents"] == 0
    assert item["reversed_amount_cents"] == 0
    assert item["reversed_credits"] == 0
    assert item["dispute_active"] is False
    assert item["requires_reversal_review"] is False
    assert item["aade_document_type"] is None
    assert item["aade_series"] is None
    assert item["aade_aa"] is None
    assert item["aade_mark"] is None
    assert item["issued_at"] is None
    assert "recorded_by_user_id" not in item
    assert item["recorded_at"] is None
    assert item["package"] == {
        "key": "starter",
        "credits": 100,
    }
    assert item["payment"] == {
        "checkout_session_id": f"cs_test_{purchase_id}",
        "payment_intent_id": f"pi_{purchase_id}",
        "confirmed_at": 1_600_000_000,
        "livemode": False,
        "amount_paid_cents": 100,
        "currency": "eur",
        "payment_status": "paid",
    }
    assert item["customer"] == {
        "name": "AADE Customer",
        "email": f"{purchase_id}@example.com",
        "country": "GR",
        "city": "Athens",
        "postal_code": "10558",
        "line1": "1 Ermou Street",
        "line2": "Floor 2",
        "state": "Attica",
        "status": "ready_for_manual_issue",
        "missing_required_fields": [],
    }
    assert item["tax"] == {
        "gross_amount_cents": 100,
        "net_amount_cents": 81,
        "vat_amount_cents": 19,
        "vat_rate_percent": 24,
    }
    assert item["service"] == {
        "code": "4",
        "name": "GSUBS Credits",
    }
    assert {
        "package_snapshot",
        "payment_snapshot",
        "customer_snapshot",
        "tax_snapshot",
        "document_snapshot",
    }.isdisjoint(item)
    assert "consumer_contract" not in item["package"]
    assert "stripe_customer_id" not in item["payment"]
    assert "tax_ids" not in item["tax"]


def test_pending_invoice_response_disables_sensitive_snapshot_caching(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)

    response = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
    )

    assert response.status_code == 200
    # REGRESSION: Admin listings contain customer/payment reconciliation data
    # and must never be retained by browser or intermediary caches.
    _assert_sensitive_admin_response_is_not_cacheable(response)


def test_pending_invoice_reconciliation_keeps_missing_legacy_payment_explicit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(
        user_id=user_id,
        legacy_missing_payment_snapshot=True,
    )

    item = _find_pending_invoice(
        client,
        headers=headers,
        invoice_id=invoice_id,
    )

    assert item["document_status"] == "manual_review_required"
    assert item["payment"] is None
    assert item["service"] == {
        "code": "4",
        "name": "GSUBS Credits",
    }


def test_pending_refunded_invoice_exposes_reversal_review_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status="partially_refunded",
        refunded_amount_cents=40,
        reversed_amount_cents=40,
        reversed_credits=40,
    )

    item = _find_pending_invoice(
        client,
        headers=headers,
        invoice_id=invoice_id,
    )

    assert item["purchase_status"] == "partially_refunded"
    assert item["refunded_amount_cents"] == 40
    assert item["reversed_amount_cents"] == 40
    assert item["reversed_credits"] == 40
    assert item["dispute_active"] is False
    assert item["requires_reversal_review"] is True


def test_issued_invoice_with_active_reversal_remains_visible_for_review(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    issued = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    assert issued.status_code == 200
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status="disputed",
        reversed_amount_cents=100,
        reversed_credits=100,
        dispute_active=True,
    )

    item = _find_pending_invoice(
        client,
        headers=headers,
        invoice_id=invoice_id,
    )

    assert item["document_status"] == "issued"
    assert item["purchase_status"] == "disputed"
    assert item["reversed_amount_cents"] == 100
    assert item["reversed_credits"] == 100
    assert item["dispute_active"] is True
    assert item["requires_reversal_review"] is True
    assert item["aade_document_type"] == payload["document_type"]
    assert item["aade_series"] == payload["series"]
    assert item["aade_aa"] == payload["aa"]
    assert item["aade_mark"] == payload["mark"]
    assert item["issued_at"] == payload["issued_at"]
    assert "recorded_by_user_id" not in item
    assert item["recorded_at"] == issued.json()["recorded_at"]


def test_resolved_issued_invoice_is_removed_from_reversal_review_queue(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    issued = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=int(time.time()) - 30),
    )
    assert issued.status_code == 200
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status="disputed",
        reversed_amount_cents=100,
        reversed_credits=100,
        dispute_active=True,
    )
    visible = _find_pending_invoice(
        client,
        headers=headers,
        invoice_id=invoice_id,
    )
    assert visible["requires_reversal_review"] is True

    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status="paid",
    )

    assert invoice_id not in _all_pending_invoice_ids(
        client,
        headers=headers,
    )


def test_pending_invoice_queue_uses_stable_keyset_pagination(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _seed_pending_invoice(user_id=user_id)

    first = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
        params={"limit": 1},
    )

    assert first.status_code == 200
    assert len(first.json()["items"]) == 1
    assert first.json()["count"] == 1
    assert first.json()["next_cursor"]

    second = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
        params={"limit": 1, "after": first.json()["next_cursor"]},
    )

    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["items"][0]["invoice_id"] != first.json()["items"][0]["invoice_id"]


@pytest.mark.parametrize(
    "cursor",
    (
        "not-a-cursor",
        "-1:0123456789abcdef0123456789abcdef",
        "1:not-hex",
    ),
)
def test_pending_invoice_queue_rejects_invalid_cursor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    cursor: str,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)

    response = client.get(
        "/billing/admin/invoices/pending",
        headers=headers,
        params={"after": cursor},
    )

    assert response.status_code == 422


def test_admin_records_already_issued_aade_document_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, original_retention = _seed_pending_invoice(
        user_id=user_id,
    )
    issued_at = int(time.time()) - 30
    payload = _issued_payload(issued_at=issued_at)

    request_started_at = int(time.time())
    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    request_finished_at = int(time.time())

    assert response.status_code == 200, response.text
    # REGRESSION: The write response contains AADE/payment identifiers and
    # needs the same cache prohibition as the snapshot listing.
    _assert_sensitive_admin_response_is_not_cacheable(response)
    response_body = response.json()
    recorded_at = response_body["recorded_at"]
    assert request_started_at <= recorded_at <= request_finished_at
    expected_retention = max(
        financial_retention_deadline(issued_at),
        financial_retention_deadline(recorded_at),
    )
    assert response_body == {
        "invoice_id": invoice_id,
        "purchase_id": purchase_id,
        "document_status": "issued",
        "aade_document_type": payload["document_type"],
        "aade_series": payload["series"],
        "aade_aa": payload["aa"],
        "aade_mark": payload["mark"],
        "issued_at": issued_at,
        "recorded_at": recorded_at,
        "financial_retention_until": expected_retention,
    }
    assert response_body["financial_retention_until"] > original_retention

    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_retention
        assert invoice.financial_retention_until == expected_retention
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at == recorded_at


def test_record_issued_waits_on_purchase_without_locking_invoice(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    db = Database()

    # REGRESSION: reversal/cleanup writers hold the purchase before touching
    # the invoice. While one does so, the admin writer must wait on that parent
    # without first taking the child lock, or the two transactions can deadlock.
    with db.engine.connect() as blocker:
        transaction = blocker.begin()
        blocker_pid = blocker.execute(
            text("SELECT pg_backend_pid()"),
        ).scalar_one()
        blocker.execute(
            text(
                """
                SELECT id
                FROM credit_purchases
                WHERE id = :purchase_id
                FOR UPDATE
                """
            ),
            {"purchase_id": purchase_id},
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(
                client.post,
                f"/billing/admin/invoices/{invoice_id}/record-issued",
                headers=headers,
                json=payload,
            )
            waiting_on_parent = False
            deadline = time.monotonic() + 10
            try:
                while time.monotonic() < deadline:
                    with db.engine.connect() as observer:
                        waiting_on_parent = bool(
                            observer.execute(
                                text(
                                    """
                                    SELECT EXISTS (
                                        SELECT 1
                                        FROM pg_stat_activity AS activity
                                        WHERE :blocker_pid = ANY(
                                            pg_blocking_pids(activity.pid)
                                        )
                                          AND activity.query ILIKE
                                              '%credit_purchases%'
                                    )
                                    """
                                ),
                                {"blocker_pid": blocker_pid},
                            ).scalar_one()
                        )
                    if waiting_on_parent or request.done():
                        break
                    time.sleep(0.05)
                assert waiting_on_parent, (
                    "Admin writer did not serialize on the locked purchase"
                )
                # This succeeds only if the waiting admin transaction has not
                # already taken the child row lock.
                blocker.execute(
                    text(
                        """
                        SELECT id
                        FROM billing_invoices
                        WHERE id = :invoice_id
                        FOR UPDATE NOWAIT
                        """
                    ),
                    {"invoice_id": invoice_id},
                )
            finally:
                transaction.rollback()

            response = request.result(timeout=10)

    assert response.status_code == 200, response.text
    assert response.json()["document_status"] == "issued"


@pytest.mark.parametrize(
    "reversal_state",
    (
        {
            "status": "partially_refunded",
            "refunded_amount_cents": 25,
            "reversed_amount_cents": 25,
            "reversed_credits": 25,
        },
        {
            "status": "paid",
            "reversed_amount_cents": 25,
        },
        {
            "status": "disputed",
            "reversed_amount_cents": 100,
            "reversed_credits": 100,
            "dispute_active": True,
        },
        {
            "status": "paid",
            "reversed_credits": 25,
        },
    ),
)
def test_record_issued_blocks_active_or_inconsistent_reversal_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    reversal_state: dict[str, str | int | bool],
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status=cast(str, reversal_state["status"]),
        refunded_amount_cents=cast(
            int,
            reversal_state.get("refunded_amount_cents", 0),
        ),
        reversed_amount_cents=cast(
            int,
            reversal_state.get("reversed_amount_cents", 0),
        ),
        reversed_credits=cast(
            int,
            reversal_state.get("reversed_credits", 0),
        ),
        dispute_active=cast(
            bool,
            reversal_state.get("dispute_active", False),
        ),
    )

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=int(time.time()) - 30),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Purchase requires reversal accounting review before recording an AADE document"
    )
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_document_type is None
        assert invoice.aade_series is None
        assert invoice.aade_aa is None
        assert invoice.aade_mark is None
        assert invoice.issued_at is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None


def test_record_issued_exact_replay_returns_existing_without_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    replay_headers, replay_user_id = _auth_headers(
        client,
        email=f"billing-admin-replay-{uuid.uuid4().hex}@example.com",
    )
    monkeypatch.setenv(
        "GSP_BILLING_ADMIN_USER_IDS",
        f"{user_id},{replay_user_id}",
    )
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200

    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at is not None
        expected_recorded_by_user_id = invoice.recorded_by_user_id
        expected_recorded_at = invoice.recorded_at
        purchase.financial_retention_until += 172_800
        invoice.financial_retention_until += 86_400
        purchase.updated_at -= 19
        invoice.updated_at -= 17
        expected_purchase_retention = purchase.financial_retention_until
        expected_invoice_retention = invoice.financial_retention_until
        expected_purchase_updated_at = purchase.updated_at
        expected_invoice_updated_at = invoice.updated_at

    replay = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=replay_headers,
        json=payload,
    )

    # REGRESSION: A successful write whose HTTP response was lost must be
    # recoverable by replaying the exact immutable AADE identity.
    assert replay.status_code == 200, replay.text
    _assert_sensitive_admin_response_is_not_cacheable(replay)
    assert replay.json() == {
        "invoice_id": invoice_id,
        "purchase_id": purchase_id,
        "document_status": "issued",
        "aade_document_type": payload["document_type"],
        "aade_series": payload["series"],
        "aade_aa": payload["aa"],
        "aade_mark": payload["mark"],
        "issued_at": payload["issued_at"],
        "recorded_at": expected_recorded_at,
        "financial_retention_until": expected_invoice_retention,
    }
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_purchase_retention
        assert invoice.financial_retention_until == expected_invoice_retention
        assert purchase.updated_at == expected_purchase_updated_at
        assert invoice.updated_at == expected_invoice_updated_at
        assert invoice.recorded_by_user_id == expected_recorded_by_user_id
        assert invoice.recorded_at == expected_recorded_at


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("document_type", "1.1"),
        ("series", "A"),
        ("aa", "999999"),
        ("mark", "9223372036854775807"),
        ("issued_at", 1_600_000_001),
    ),
)
def test_record_issued_mismatched_replay_is_conflict_and_does_not_overwrite(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str | int,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    first_payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=first_payload,
    )
    assert first.status_code == 200
    replay_payload = dict(first_payload)
    replay_payload[field] = replacement

    replay = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=replay_payload,
    )

    assert replay.status_code == 409
    assert replay.json()["detail"] == "AADE document has already been recorded"
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.aade_document_type == first_payload["document_type"]
        assert invoice.aade_series == first_payload["series"]
        assert invoice.aade_aa == first_payload["aa"]
        assert invoice.aade_mark == first_payload["mark"]
        assert invoice.issued_at == first_payload["issued_at"]
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at == first.json()["recorded_at"]


def test_record_issued_exact_replay_does_not_bypass_reversal_review(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status="disputed",
        reversed_amount_cents=100,
        reversed_credits=100,
        dispute_active=True,
    )
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        expected_purchase_retention = purchase.financial_retention_until
        expected_invoice_retention = invoice.financial_retention_until
        expected_purchase_updated_at = purchase.updated_at
        expected_invoice_updated_at = invoice.updated_at

    replay = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert replay.status_code == 409
    assert replay.json()["detail"] == (
        "Purchase requires reversal accounting review before recording an AADE document"
    )
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_purchase_retention
        assert invoice.financial_retention_until == expected_invoice_retention
        assert purchase.updated_at == expected_purchase_updated_at
        assert invoice.updated_at == expected_invoice_updated_at


def test_record_issued_rejects_incomplete_identity_without_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    incomplete = _issued_payload(issued_at=int(time.time()) - 30)
    incomplete.pop("mark")

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=incomplete,
    )

    assert response.status_code == 422
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_mark is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("document_type", "1.1"),
        ("series", "A"),
    ),
)
def test_record_issued_rejects_non_mizai_accounting_baseline_without_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    payload[field] = replacement
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        expected_purchase_retention = purchase.financial_retention_until
        expected_invoice_retention = invoice.financial_retention_until
        expected_purchase_updated_at = purchase.updated_at
        expected_invoice_updated_at = invoice.updated_at

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "AADE document type and series must match the approved Greek B2C baseline"
    )
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_purchase_retention
        assert invoice.financial_retention_until == expected_invoice_retention
        assert purchase.updated_at == expected_purchase_updated_at
        assert invoice.updated_at == expected_invoice_updated_at
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_document_type is None
        assert invoice.aade_series is None
        assert invoice.aade_aa is None
        assert invoice.aade_mark is None
        assert invoice.issued_at is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("document_type", "../11.2"),
        ("series", " "),
        ("series", "A B"),
        ("series", "X" * 33),
        ("aa", "AA-1"),
        ("mark", "MARK-1"),
        ("issued_at", 0),
    ),
)
def test_record_issued_strictly_validates_bounded_identity_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str | int,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    payload[field] = value

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "mark",
    (
        "0",
        "0400014466064287",
        "10000000000000000000",
        "9223372036854775808",
    ),
)
def test_record_issued_rejects_noncanonical_or_out_of_range_aade_mark(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mark: str,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    payload["mark"] = mark

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    # REGRESSION: AADE specifies MARK as xs:long. Accepting arbitrary digit
    # strings allowed zero/leading-zero aliases and values outside int64.
    assert response.status_code == 422
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_mark is None


def test_record_issued_accepts_canonical_existing_style_aade_mark(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    existing_style_mark = f"4{uuid.uuid4().int % 10**14:014d}"
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    payload["mark"] = existing_style_mark

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["aade_mark"] == existing_style_mark


def test_record_issued_rejects_future_timestamp(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=int(time.time()) + 3600),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "AADE issued_at cannot be in the future"


def test_record_issued_rejects_timestamp_before_confirmed_payment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=1_500_000_000),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ("AADE issued_at cannot predate the confirmed payment")


def test_record_issued_rejects_timestamp_between_creation_and_payment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    payment_confirmation_at = int(time.time()) - 60
    _, invoice_id, _ = _seed_pending_invoice(
        user_id=user_id,
        payment_confirmation_at=payment_confirmation_at,
    )

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(
            issued_at=payment_confirmation_at - 1,
        ),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ("AADE issued_at cannot predate the confirmed payment")


def test_legacy_manual_review_uses_fulfillment_timestamp_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(
        user_id=user_id,
        legacy_missing_payment_snapshot=True,
    )
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        assert purchase.fulfilled_at is not None
        fallback_confirmation_at = purchase.fulfilled_at

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=fallback_confirmation_at),
    )

    assert response.status_code == 200
    assert response.json()["issued_at"] == fallback_confirmation_at


def test_legacy_payment_intent_without_fulfillment_proof_stays_manual_review(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, original_retention = _seed_pending_invoice(
        user_id=user_id,
        legacy_missing_payment_snapshot=True,
        purchase_fulfilled=False,
    )
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        assert purchase.payment_intent_id is not None
        assert purchase.payment_snapshot is None
        assert purchase.fulfilled_at is None

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=int(time.time()) - 30),
    )

    # REGRESSION: A legacy payment-intent identifier and row creation time are
    # not evidence that Stripe payment fulfillment actually completed.
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Stripe payment fulfillment timestamp is unavailable"
    )
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == original_retention
        assert invoice.financial_retention_until == original_retention
        assert invoice.document_status == "manual_review_required"
        assert invoice.aade_document_type is None
        assert invoice.aade_series is None
        assert invoice.aade_aa is None
        assert invoice.aade_mark is None
        assert invoice.issued_at is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None


def test_record_issued_returns_not_found_for_unknown_invoice(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)

    response = client.post(
        f"/billing/admin/invoices/{uuid.uuid4().hex}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=int(time.time()) - 30),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Billing invoice not found"


def test_record_issued_conflicts_with_existing_aade_identity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, first_invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    _, second_invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{first_invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200

    conflict = client.post(
        f"/billing/admin/invoices/{second_invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == ("AADE document identity conflicts with an existing record")


def test_record_issued_never_shortens_existing_retention(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    issued_at = int(time.time()) - 30
    longer_retention = financial_retention_deadline(issued_at) + 86_400
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        purchase.financial_retention_until = longer_retention
        invoice.financial_retention_until = longer_retention

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=issued_at),
    )

    assert response.status_code == 200
    assert response.json()["financial_retention_until"] == longer_retention
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        assert purchase.financial_retention_until == longer_retention
