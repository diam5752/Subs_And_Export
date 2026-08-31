from __future__ import annotations

from backend.tests.billing_admin_test_support import (
    Database,
    DBAPIError,
    DbBillingAdjustmentRecord,
    DbBillingInvoice,
    DbCreditPurchase,
    TestClient,
    _all_pending_review_ids,
    _allow_billing_admin,
    _assert_sensitive_admin_response_is_not_cacheable,
    _auth_headers,
    _find_pending_review,
    _manual_refund_accounting_payload,
    _seed_completed_stripe_refund,
    _seed_pending_invoice,
    pytest,
    select,
    text,
    time,
    uuid,
)


def test_pending_refund_queue_lists_only_completed_unrecorded_stripe_refunds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    refund_at = int(time.time()) - 90
    reversal_id, stripe_refund_id = _seed_completed_stripe_refund(
        purchase_id=purchase_id,
        provider_event_created=refund_at,
    )

    response = client.get(
        "/billing/admin/refunds/pending",
        headers=headers,
    )
    assert response.status_code == 200
    _assert_sensitive_admin_response_is_not_cacheable(response)
    item = _find_pending_review(
        client,
        headers=headers,
        resource="refunds",
        identity_key="reversal_id",
        identity_value=reversal_id,
    )
    assert item["stripe_refund_id"] == stripe_refund_id
    assert item["stripe_refund_status"] == "succeeded"
    assert item["stripe_refund_created_at"] == refund_at
    assert item["amount_cents"] == 100
    assert item["currency"] == "eur"
    assert item["linked_withdrawal_id"] is None
    assert item["original_invoice"]["invoice_id"] == invoice_id
    assert item["original_invoice"]["purchase_id"] == purchase_id
    assert "stripe_customer_id" not in response.text
    assert "consumer_contract" not in response.text
    assert "recorded_by_user_id" not in response.text


def test_manual_refund_accounting_is_append_only_exactly_replayable_and_local(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    refund_at = int(time.time()) - 90
    reversal_id, stripe_refund_id = _seed_completed_stripe_refund(
        purchase_id=purchase_id,
        provider_event_created=refund_at,
    )
    payload = _manual_refund_accounting_payload(
        payment_at=1_600_000_000,
        refund_at=refund_at,
    )

    recorded = client.post(
        (f"/billing/admin/refunds/{reversal_id}/record-aade-adjustment"),
        headers=headers,
        json=payload,
    )

    assert recorded.status_code == 200, recorded.text
    _assert_sensitive_admin_response_is_not_cacheable(recorded)
    result = recorded.json()
    assert result["purchase_id"] == purchase_id
    assert result["reversal_id"] == reversal_id
    assert result["stripe_refund_id"] == stripe_refund_id
    assert result["original_invoice_status"] == "issued"
    assert result["original_invoice_mark"] == (payload["original_document"]["mark"])
    assert result["aade_document_type"] == "11.4"
    assert result["aade_mark"] == (payload["adjustment_document"]["mark"])

    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        adjustment = session.get(
            DbBillingAdjustmentRecord,
            result["adjustment_id"],
        )
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert invoice is not None
        assert adjustment is not None
        assert purchase is not None
        assert invoice.document_status == "issued"
        assert invoice.recorded_by_user_id == user_id
        assert adjustment.recorded_by_user_id == user_id
        assert adjustment.document_snapshot["automatic_stripe_refund_executed"] is False
        assert adjustment.document_snapshot["automatic_aade_adjustment_executed"] is False
        assert adjustment.financial_retention_until >= (result["financial_retention_until"])
        assert invoice.financial_retention_until >= (adjustment.financial_retention_until)
        assert purchase.financial_retention_until >= (adjustment.financial_retention_until)

    replay = client.post(
        (f"/billing/admin/refunds/{reversal_id}/record-aade-adjustment"),
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 200
    assert replay.json() == result

    conflicting_payload = {
        **payload,
        "adjustment_document": {
            **payload["adjustment_document"],
            "mark": f"6{uuid.uuid4().int % 10**15:015d}",
        },
    }
    conflict = client.post(
        (f"/billing/admin/refunds/{reversal_id}/record-aade-adjustment"),
        headers=headers,
        json=conflicting_payload,
    )
    assert conflict.status_code == 409
    assert "different evidence" in conflict.json()["detail"]

    assert reversal_id not in _all_pending_review_ids(
        client,
        headers=headers,
        resource="refunds",
        identity_key="reversal_id",
    )

    with pytest.raises(DBAPIError, match="append-only"):
        with db.session() as session:
            session.execute(
                text(
                    """
                    UPDATE billing_adjustment_records
                    SET aade_mark = :mark
                    WHERE id = :adjustment_id
                    """
                ),
                {
                    "mark": f"7{uuid.uuid4().int % 10**15:015d}",
                    "adjustment_id": result["adjustment_id"],
                },
            )


def test_failed_or_inactive_refund_cannot_record_aade_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, original_retention = _seed_pending_invoice(
        user_id=user_id,
    )
    refund_at = int(time.time()) - 90
    reversal_id, _ = _seed_completed_stripe_refund(
        purchase_id=purchase_id,
        provider_event_created=refund_at,
        status="failed",
        active=False,
    )
    payload = _manual_refund_accounting_payload(
        payment_at=1_600_000_000,
        refund_at=refund_at,
    )

    response = client.post(
        (f"/billing/admin/refunds/{reversal_id}/record-aade-adjustment"),
        headers=headers,
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == ("A completed Stripe refund is required")
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_mark is None
        assert invoice.financial_retention_until == original_retention
        assert (
            session.scalar(
                select(DbBillingAdjustmentRecord).where(
                    DbBillingAdjustmentRecord.reversal_id == reversal_id,
                )
            )
            is None
        )
