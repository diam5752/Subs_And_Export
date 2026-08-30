from __future__ import annotations

from backend.tests.services.billing_test_support import (
    BillingConflictError,
    DbStripeWebhookEvent,
    _checkout_event,
    _process,
    _purchase,
    _service,
    hashlib,
    json,
    pytest,
    replace,
    time,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_webhook_retry_ignores_pending_delivery_count(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    event_id = f"evt_{uuid.uuid4().hex}"
    initial = json.loads(_checkout_event(purchase, event_id=event_id))
    initial["pending_webhooks"] = 2
    retry = json.loads(json.dumps(initial))
    retry["pending_webhooks"] = 1

    assert _process(service, initial) == "processed"
    assert _process(service, retry) == "duplicate"
    assert len(gateway.capture_calls) == 1
    assert points.get_balances(user_id).paid_balance == 100


def test_legacy_webhook_hash_recovers_canceled_authorization_retry(
    billing_settings: None,
) -> None:
    # Legacy receipts hashed the whole envelope. Upgrade only when Stripe's
    # pending_webhooks delivery counter is the sole byte-level difference.
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    payment_intent_id = f"pi_{purchase.id}"
    gateway.payment_intent_states[payment_intent_id] = replace(
        gateway.payment_intent_states[payment_intent_id],
        status="canceled",
    )
    event_id = f"evt_{uuid.uuid4().hex}"
    initial = json.loads(_checkout_event(purchase, event_id=event_id))
    initial["pending_webhooks"] = 2
    initial_payload = json.dumps(initial, sort_keys=True).encode()
    retry = json.loads(json.dumps(initial))
    retry["pending_webhooks"] = 1
    with db.session() as session:
        session.add(
            DbStripeWebhookEvent(
                id=event_id,
                event_type="checkout.session.completed",
                payload_sha256=hashlib.sha256(initial_payload).hexdigest(),
                status="error",
                error="legacy capture failure",
                created_at=int(time.time()),
                processed_at=None,
            )
        )

    tampered_retry = json.loads(json.dumps(retry))
    tampered_retry["data"]["object"]["amount_total"] = 101
    with pytest.raises(BillingConflictError, match="different data"):
        _process(service, tampered_retry)
    assert points.get_balances(user_id).paid_balance == 0

    assert _process(service, retry) == "processed"
    persisted = _purchase(db, purchase.id)
    assert persisted.status == "failed"
    assert points.get_balances(user_id).paid_balance == 0
    with db.session() as session:
        receipt = session.get(DbStripeWebhookEvent, event_id)
        assert receipt is not None
        assert receipt.status == "processed"
        assert receipt.payload_sha256 != hashlib.sha256(initial_payload).hexdigest()
