from __future__ import annotations

from backend.tests.billing_admin_test_support import (
    Database,
    DbBillingInvoice,
    DbCreditPurchase,
    TestClient,
    _allow_billing_admin,
    _auth_headers,
    _issued_payload,
    _seed_pending_invoice,
    financial_retention_deadline,
    pytest,
    time,
    uuid,
)


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
    assert response.json()["detail"] == ("Stripe payment fulfillment timestamp is unavailable")
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
