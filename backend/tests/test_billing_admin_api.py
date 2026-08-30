from __future__ import annotations

from backend.tests.billing_admin_test_support import (
    Database,
    DbBillingInvoice,
    TestClient,
    _all_pending_invoice_ids,
    _allow_billing_admin,
    _assert_sensitive_admin_response_is_not_cacheable,
    _auth_headers,
    _find_pending_invoice,
    _issued_payload,
    _seed_pending_invoice,
    _set_purchase_reversal_state,
    pytest,
    time,
    uuid,
)


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
