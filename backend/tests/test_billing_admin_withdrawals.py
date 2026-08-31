from __future__ import annotations

from backend.tests.billing_admin_test_support import (
    Database,
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingWithdrawalResolution,
    TestClient,
    _all_pending_review_ids,
    _allow_billing_admin,
    _assert_sensitive_admin_response_is_not_cacheable,
    _auth_headers,
    _canonical_consumer_contract_snapshot,
    _find_pending_review,
    _manual_refund_accounting_payload,
    _seed_completed_stripe_refund,
    _seed_contract_and_withdrawal,
    _seed_pending_invoice,
    pytest,
    select,
    time,
    uuid,
)


def test_accepted_withdrawal_requires_and_exposes_completed_manual_actions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    now = int(time.time())
    purchase_id, _, _ = _seed_pending_invoice(
        user_id=user_id,
        consumer_contract_snapshot=(
            _canonical_consumer_contract_snapshot(
                accepted_at=now - 182,
            )
        ),
    )
    withdrawal_id = _seed_contract_and_withdrawal(
        purchase_id=purchase_id,
        user_id=user_id,
        email=email,
        submitted_at=now - 180,
    )

    pending_before = _find_pending_review(
        client,
        headers=headers,
        resource="withdrawals",
        identity_key="withdrawal_id",
        identity_value=withdrawal_id,
    )
    assert pending_before["available_adjustments"] == []
    assert pending_before["confirmation_email"] == email

    no_evidence = client.post(
        f"/billing/admin/withdrawals/{withdrawal_id}/resolve",
        headers=headers,
        json={
            "decision": "accepted_refunded",
            "adjustment_id": uuid.uuid4().hex,
            "customer_explanation": ("Η αίτησή σας εγκρίθηκε μετά από ανθρώπινο έλεγχο."),
            "final_manual_review_confirmed": True,
        },
    )
    assert no_evidence.status_code == 409
    assert no_evidence.json()["detail"] == ("Accepted withdrawal adjustment was not found")

    refund_at = now - 90
    reversal_id, stripe_refund_id = _seed_completed_stripe_refund(
        purchase_id=purchase_id,
        provider_event_created=refund_at,
    )
    accounting_payload = _manual_refund_accounting_payload(
        payment_at=1_600_000_000,
        refund_at=refund_at,
    )
    accounting = client.post(
        (f"/billing/admin/refunds/{reversal_id}/record-aade-adjustment"),
        headers=headers,
        json=accounting_payload,
    )
    assert accounting.status_code == 200, accounting.text
    adjustment_id = accounting.json()["adjustment_id"]

    pending_after = _find_pending_review(
        client,
        headers=headers,
        resource="withdrawals",
        identity_key="withdrawal_id",
        identity_value=withdrawal_id,
    )
    assert pending_after["available_adjustments"] == [
        {
            "adjustment_id": adjustment_id,
            "stripe_refund_id": stripe_refund_id,
            "amount_cents": 100,
            "currency": "eur",
            "aade_document_type": (accounting_payload["adjustment_document"]["document_type"]),
            "aade_series": (accounting_payload["adjustment_document"]["series"]),
            "aade_aa": (accounting_payload["adjustment_document"]["aa"]),
            "aade_mark": (accounting_payload["adjustment_document"]["mark"]),
            "issued_at": (accounting_payload["adjustment_document"]["issued_at"]),
        }
    ]

    explanation = "Η αίτησή σας εγκρίθηκε μετά από ανθρώπινο έλεγχο και η επιστροφή ολοκληρώθηκε χειροκίνητα."
    resolution_payload = {
        "decision": "accepted_refunded",
        "adjustment_id": adjustment_id,
        "customer_explanation": explanation,
        "final_manual_review_confirmed": True,
    }
    resolved = client.post(
        f"/billing/admin/withdrawals/{withdrawal_id}/resolve",
        headers=headers,
        json=resolution_payload,
    )

    assert resolved.status_code == 200, resolved.text
    _assert_sensitive_admin_response_is_not_cacheable(resolved)
    resolution = resolved.json()
    assert resolution["decision"] == "accepted_refunded"
    assert resolution["reason_code"] == "statutory_right_accepted"
    assert resolution["adjustment_id"] == adjustment_id
    assert resolution["resolution_url"] == (f"/billing/purchases/{purchase_id}/withdrawal-resolution")

    replay = client.post(
        f"/billing/admin/withdrawals/{withdrawal_id}/resolve",
        headers=headers,
        json=resolution_payload,
    )
    assert replay.status_code == 200
    assert replay.json() == resolution

    conflict = client.post(
        f"/billing/admin/withdrawals/{withdrawal_id}/resolve",
        headers=headers,
        json={
            **resolution_payload,
            "customer_explanation": ("Διαφορετική τελική αιτιολογία που δεν αποτελεί replay."),
        },
    )
    assert conflict.status_code == 409
    assert "different evidence" in conflict.json()["detail"]

    purchases = client.get("/billing/purchases", headers=headers)
    assert purchases.status_code == 200
    purchase = next(item for item in purchases.json() if item["purchase_id"] == purchase_id)
    assert purchase["withdrawal_status"] == "accepted_refunded"
    assert purchase["withdrawal_resolution_available"] is True
    assert purchase["withdrawal_resolution_decision"] == "accepted_refunded"
    assert purchase["withdrawal_resolution_url"] == (f"/billing/purchases/{purchase_id}/withdrawal-resolution")

    artifact = client.get(
        purchase["withdrawal_resolution_url"],
        headers=headers,
    )
    assert artifact.status_code == 200
    assert artifact.headers["cache-control"] == "private, no-store"
    document = artifact.json()
    assert document["customer_explanation"] == explanation
    assert document["mandatory_consumer_rights_preserved"] is True
    assert document["manual_actions"]["performed_automatically"] is False
    assert document["manual_actions"]["stripe_refund_id"] == (stripe_refund_id)
    assert document["manual_actions"]["aade_adjustment_id"] == (adjustment_id)

    assert withdrawal_id not in _all_pending_review_ids(
        client,
        headers=headers,
        resource="withdrawals",
        identity_key="withdrawal_id",
    )
    db = Database()
    with db.session() as session:
        stored = session.get(
            DbBillingWithdrawalResolution,
            resolution["resolution_id"],
        )
        assert stored is not None
        assert stored.resolved_by_user_id == user_id
        assert stored.financial_retention_until > stored.resolved_at


def test_rejected_withdrawal_records_no_refund_or_aade_action(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    submitted_at = int(time.time()) - 60
    purchase_id, _, _ = _seed_pending_invoice(
        user_id=user_id,
        consumer_contract_snapshot=(
            _canonical_consumer_contract_snapshot(
                accepted_at=submitted_at - 2,
            )
        ),
    )
    withdrawal_id = _seed_contract_and_withdrawal(
        purchase_id=purchase_id,
        user_id=user_id,
        email=email,
        submitted_at=submitted_at,
    )
    explanation = "Η αίτηση εξετάστηκε χειροκίνητα και δεν πληροί τις προϋποθέσεις της υποχρεωτικής επιστροφής."

    resolved = client.post(
        f"/billing/admin/withdrawals/{withdrawal_id}/resolve",
        headers=headers,
        json={
            "decision": "rejected",
            "adjustment_id": None,
            "customer_explanation": explanation,
            "final_manual_review_confirmed": True,
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["decision"] == "rejected"
    assert resolved.json()["reason_code"] == "request_not_eligible"
    assert resolved.json()["adjustment_id"] is None
    artifact = client.get(
        (f"/billing/purchases/{purchase_id}/withdrawal-resolution"),
        headers=headers,
    )
    assert artifact.status_code == 200
    assert artifact.json()["manual_actions"] is None
    assert artifact.json()["mandatory_consumer_rights_preserved"] is True
    db = Database()
    with db.session() as session:
        adjustments = tuple(
            session.scalars(
                select(DbBillingAdjustmentRecord).where(
                    DbBillingAdjustmentRecord.purchase_id == purchase_id,
                )
            )
        )
        assert adjustments == ()
        confirmation = session.scalar(
            select(DbBillingContractConfirmation).where(
                DbBillingContractConfirmation.purchase_id == purchase_id,
            )
        )
        assert confirmation is not None
