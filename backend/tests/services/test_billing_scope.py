from __future__ import annotations

from backend.tests.services.billing_test_support import (
    Any,
    BillingProviderError,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbPointTransaction,
    DbUser,
    DbUserPoints,
    IntegrityError,
    _checkout_event,
    _dispute_event,
    _process,
    _purchase,
    _refund_event,
    _refund_object_event,
    _service,
    billing_module,
    pytest,
    select,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_foreign_refund_is_ignored_after_payment_intent_namespace_lookup(
    billing_settings: None,
) -> None:
    db, _, _, gateway, service = _service()
    foreign_payment_intent_id = f"pi_{uuid.uuid4().hex}"
    gateway.payment_intent_metadata[foreign_payment_intent_id] = {
        "purchase_id": uuid.uuid4().hex,
        "integration_identifier": "mizai_credits_abcdefgh",
    }
    placeholder = DbCreditPurchase(
        id=uuid.uuid4().hex,
        user_id=None,
        account_reference_hash=None,
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"placeholder-{uuid.uuid4().hex}",
        checkout_session_id=None,
        checkout_url=None,
        payment_intent_id=None,
        integration_identifier="gsubs_credits_abcdefgh",
        status="creating",
        fulfilled_at=None,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot={},
        payment_snapshot=None,
        customer_snapshot=None,
        tax_snapshot=None,
        financial_retention_until=1,
        error=None,
        created_at=1,
        updated_at=1,
    )
    event = _refund_object_event(
        placeholder,
        payment_intent_id=foreign_payment_intent_id,
    )
    foreign_reversal_id = str(event["data"]["object"]["id"])

    assert _process(service, event) == "ignored"
    assert gateway.payment_intent_lookup_calls == [foreign_payment_intent_id]
    with db.session() as session:
        # REGRESSION: this assertion must be scoped to the foreign event;
        # the shared integration database can legitimately contain reversals
        # created by earlier tests.
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.provider_reversal_id == foreign_reversal_id
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "event_type",
    (
        "refund.created",
        "charge.refunded",
        "charge.dispute.created",
    ),
)
def test_foreign_reversal_without_payment_intent_is_ignored_without_lookup(
    billing_settings: None,
    event_type: str,
) -> None:
    db, _, _, gateway, service = _service()
    object_id = (
        f"re_{uuid.uuid4().hex}"
        if event_type == "refund.created"
        else (f"ch_{uuid.uuid4().hex}" if event_type == "charge.refunded" else f"dp_{uuid.uuid4().hex}")
    )
    obj: dict[str, Any] = {
        "id": object_id,
        "payment_intent": None,
        "currency": "eur",
        "status": ("succeeded" if event_type == "refund.created" else "needs_response"),
    }
    if event_type == "charge.refunded":
        obj["amount_refunded"] = 40
    else:
        obj["amount"] = 40
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "created": 1_700_003_575,
        "livemode": False,
        "data": {"object": obj},
    }

    assert _process(service, event) == "ignored"
    assert gateway.payment_intent_lookup_calls == []
    assert gateway.refund_list_calls == []
    with db.session() as session:
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.provider_reversal_id == object_id,
                )
            )
            is None
        )


def test_known_local_refund_without_payment_intent_uses_persisted_purchase_scope(
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
    assert _process(service, _checkout_event(purchase)) == "processed"
    refund_id = f"re_{uuid.uuid4().hex}"
    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="succeeded",
                created=1_700_003_580,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 60

    no_payment_intent = _refund_object_event(
        purchase,
        refund_id=refund_id,
        amount_cents=40,
        status="failed",
        event_type="refund.failed",
        created=1_700_003_590,
    )
    no_payment_intent["data"]["object"]["payment_intent"] = None

    assert _process(service, no_payment_intent) == "processed"
    assert gateway.payment_intent_lookup_calls == []
    assert points.get_balances(user_id).paid_balance == 100
    with db.session() as session:
        reversal = session.scalar(
            select(DbCreditPurchaseReversal).where(
                DbCreditPurchaseReversal.provider_reversal_id == refund_id,
            )
        )
    assert reversal is not None
    assert (reversal.status, reversal.active) == ("failed", False)


def test_local_refund_before_fulfillment_uses_payment_intent_metadata_and_reduces_grant(
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
    payment_intent_id = f"pi_{purchase.id}"
    gateway.payment_intent_metadata[payment_intent_id] = {
        "purchase_id": purchase.id,
        "integration_identifier": purchase.integration_identifier,
    }
    refund = _refund_object_event(
        purchase,
        payment_intent_id=payment_intent_id,
        amount_cents=40,
        status="succeeded",
        created=1_700_003_600,
    )

    assert _process(service, refund) == "processed"
    before_fulfillment = _purchase(db, purchase.id)
    assert before_fulfillment.payment_intent_id == payment_intent_id
    assert before_fulfillment.fulfilled_at is None
    assert before_fulfillment.reversed_credits == 40
    assert points.get_balances(user_id).paid_balance == 0

    assert _process(service, _checkout_event(before_fulfillment)) == "processed"
    assert points.get_balances(user_id).paid_balance == 60
    assert _purchase(db, purchase.id).status == "partially_refunded"


def test_local_refund_lookup_failure_is_fail_closed_and_retryable(
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
    payment_intent_id = f"pi_{purchase.id}"
    event = _refund_object_event(
        purchase,
        payment_intent_id=payment_intent_id,
        event_id=f"evt_{uuid.uuid4().hex}",
    )
    gateway.payment_intent_lookup_error = RuntimeError("provider unavailable")

    with pytest.raises(BillingProviderError, match="PaymentIntent lookup"):
        _process(service, event)
    assert points.get_balances(user_id).paid_balance == 0
    assert _purchase(db, purchase.id).payment_intent_id is None

    gateway.payment_intent_lookup_error = None
    gateway.payment_intent_metadata[payment_intent_id] = {
        "purchase_id": purchase.id,
        "integration_identifier": purchase.integration_identifier,
    }
    assert _process(service, event) == "processed"
    assert _purchase(db, purchase.id).reversed_credits == 40


def test_async_payment_failure_marks_purchase_failed_without_crediting_wallet(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user_id, points, _, service = _service()
    current_capture_policy = billing_module.MANUAL_CAPTURE_POLICY
    monkeypatch.setattr(
        billing_module,
        "MANUAL_CAPTURE_POLICY",
        "legacy_automatic_capture",
    )
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    monkeypatch.setattr(
        billing_module,
        "MANUAL_CAPTURE_POLICY",
        current_capture_policy,
    )
    purchase = _purchase(db, checkout.purchase_id)
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.async_payment_failed",
        "livemode": False,
        "data": {"object": {"id": purchase.checkout_session_id}},
    }

    # REGRESSION: a failed delayed payment previously remained checkout_created,
    # even though Stripe had reported a terminal payment failure.
    assert _process(service, event) == "processed"
    assert _purchase(db, purchase.id).status == "failed"
    assert points.get_balances(user_id).paid_balance == 0

    late_unpaid_completion = _checkout_event(
        purchase,
        payment_status="unpaid",
        include_payment_intent=False,
    )
    assert _process(service, late_unpaid_completion) == "processed"
    assert _purchase(db, purchase.id).status == "failed"
    assert points.get_balances(user_id).paid_balance == 0


def test_payment_intent_cannot_fulfill_two_purchases(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    first = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    second = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    shared_payment_intent = f"pi_{uuid.uuid4().hex}"
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, first.purchase_id)
        assert purchase is not None
        purchase.payment_intent_id = shared_payment_intent

    with pytest.raises(IntegrityError):
        with db.session() as session:
            purchase = session.get(DbCreditPurchase, second.purchase_id)
            assert purchase is not None
            purchase.payment_intent_id = shared_payment_intent


def test_won_dispute_restores_payment_without_free_reuse(
    billing_settings: None,
) -> None:
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    _process(service, _checkout_event(purchase))
    points.spend(user_id, 100, reason="transcription", require_paid=True)

    created = _dispute_event(
        purchase,
        event_type="charge.dispute.created",
        status="needs_response",
        created=1_700_004_100,
    )
    _process(service, created)
    assert points.get_balances(user_id).reversal_debt == 100

    won = _dispute_event(
        purchase,
        event_type="charge.dispute.closed",
        status="won",
        created=1_700_004_200,
    )
    _process(service, won)
    wallet = points.get_balances(user_id)
    assert wallet.reversal_debt == 0
    assert wallet.paid_balance == 0
    assert _purchase(db, purchase.id).status == "paid"


def test_reinstated_then_lost_dispute_claws_credits_back_again(
    billing_settings: None,
) -> None:
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    _process(service, _checkout_event(purchase))

    _process(
        service,
        _dispute_event(
            purchase,
            event_type="charge.dispute.created",
            status="needs_response",
            created=1_700_005_100,
        ),
    )
    assert points.get_balances(user_id).paid_balance == 0

    _process(
        service,
        _dispute_event(
            purchase,
            event_type="charge.dispute.funds_reinstated",
            status="under_review",
            created=1_700_005_200,
        ),
    )
    assert points.get_balances(user_id).paid_balance == 100

    _process(
        service,
        _dispute_event(
            purchase,
            event_type="charge.dispute.closed",
            status="lost",
            created=1_700_005_300,
        ),
    )
    wallet = points.get_balances(user_id)
    assert wallet.paid_balance == 0
    assert wallet.reversal_debt == 0
    assert _purchase(db, purchase.id).status == "disputed"


def test_deleted_account_reversal_updates_financial_state_without_wallet(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(service, _checkout_event(purchase)) == "processed"
    with db.session() as session:
        user = session.get(DbUser, user_id)
        assert user is not None
        session.delete(user)

    assert _process(service, _refund_event(purchase)) == "processed"
    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        wallet = session.get(DbUserPoints, user_id)
        reversal = session.scalar(
            select(DbCreditPurchaseReversal).where(
                DbCreditPurchaseReversal.purchase_id == purchase.id,
            )
        )

    assert persisted.user_id is None
    assert persisted.status == "reversed"
    assert persisted.reversed_credits == 100
    assert persisted.reversal_debt_credits == 0
    assert wallet is None
    assert reversal is not None


def test_reversal_wallet_and_provider_state_rollback_and_retry_atomically(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(service, _checkout_event(purchase)) == "processed"
    event = _refund_event(purchase)
    original = points.reverse_paid_purchase_once_in_session

    def mutate_then_fail(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("forced reversal transaction rollback")

    monkeypatch.setattr(
        points,
        "reverse_paid_purchase_once_in_session",
        mutate_then_fail,
    )
    with pytest.raises(RuntimeError, match="forced reversal transaction rollback"):
        _process(service, event)

    assert points.get_balances(user_id).paid_balance == 100
    with db.session() as session:
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
            is None
        )
        rollback_transactions = list(
            session.scalars(
                select(DbPointTransaction).where(
                    DbPointTransaction.reason == "stripe_reversal",
                )
            )
        )
        assert not any(
            isinstance(transaction.meta, dict) and transaction.meta.get("purchase_id") == purchase.id
            for transaction in rollback_transactions
        )

    monkeypatch.setattr(
        points,
        "reverse_paid_purchase_once_in_session",
        original,
    )
    assert _process(service, event) == "processed"
    assert points.get_balances(user_id).paid_balance == 0
    with db.session() as session:
        reversals = list(
            session.scalars(
                select(DbCreditPurchaseReversal).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
        )
        candidate_transactions = list(
            session.scalars(
                select(DbPointTransaction).where(
                    DbPointTransaction.reason == "stripe_reversal",
                )
            )
        )
        transactions = [
            transaction
            for transaction in candidate_transactions
            if isinstance(transaction.meta, dict) and transaction.meta.get("purchase_id") == purchase.id
        ]
    assert len(reversals) == 2
    assert len(transactions) == 1
