from __future__ import annotations

from backend.tests.services.billing_test_support import (
    BillingProviderError,
    DbCreditPurchaseReversal,
    DbPointTransaction,
    DbStripeWebhookEvent,
    FakeBillingGateway,
    StripeRefundState,
    ThreadPoolExecutor,
    _checkout_event,
    _process,
    _provider_refund,
    _purchase,
    _refund_event,
    _refund_object_event,
    _service,
    pytest,
    select,
    threading,
    time,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_failed_individual_refund_overrides_stale_charge_summary(
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
    refund_id = f"re_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"
    refund_state = StripeRefundState(
        id=refund_id,
        payment_intent_id=f"pi_{purchase.id}",
        amount_cents=40,
        currency=purchase.currency,
        status="succeeded",
        created=1_700_001_710,
    )
    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=40,
                created=1_700_001_710,
                refunds=[refund_state],
            ),
        )
        == "processed"
    )
    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="succeeded",
                created=1_700_001_720,
            ),
        )
        == "processed"
    )
    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="failed",
                event_type="refund.failed",
                created=1_700_001_730,
            ),
        )
        == "processed"
    )

    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 0
    assert persisted.reversed_amount_cents == 0
    assert persisted.reversed_credits == 0
    assert points.get_balances(user_id).paid_balance == 100


def test_charge_refund_reconciles_all_provider_pages_before_wallet_mutation(
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
    payment_intent_id = f"pi_{purchase.id}"
    first_refund = _provider_refund(
        purchase,
        amount_cents=40,
        created=1_700_001_740,
    )
    second_refund = _provider_refund(
        purchase,
        amount_cents=30,
        created=1_700_001_741,
    )
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        [first_refund],
        [second_refund],
    ]

    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=70,
                created=1_700_001_750,
            ),
        )
        == "processed"
    )
    assert gateway.refund_list_calls == [payment_intent_id]
    assert points.get_balances(user_id).paid_balance == 30
    assert _purchase(db, purchase.id).refunded_amount_cents == 70

    # Only one object webhook has arrived, but the complete provider list keeps
    # the still-undelivered second refund in the authoritative aggregate.
    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=first_refund.id,
                amount_cents=40,
                status="succeeded",
                created=1_700_001_760,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 30
    assert _purchase(db, purchase.id).refunded_amount_cents == 70


def test_charge_refund_reconciliation_materializes_more_than_one_hundred_refunds(
    billing_settings: None,
) -> None:
    gateway = FakeBillingGateway()
    gateway.amount_total = 300
    db, user_id, points, _, service = _service(gateway=gateway)
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="core",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(service, _checkout_event(purchase)) == "processed"
    payment_intent_id = f"pi_{purchase.id}"
    refunds = [
        _provider_refund(
            purchase,
            amount_cents=1,
            created=1_700_001_800 + index,
        )
        for index in range(101)
    ]
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        refunds[:100],
        refunds[100:],
    ]

    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=101,
                created=1_700_002_000,
            ),
        )
        == "processed"
    )

    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        individual_count = len(
            list(
                session.scalars(
                    select(DbCreditPurchaseReversal).where(
                        DbCreditPurchaseReversal.purchase_id == purchase.id,
                        DbCreditPurchaseReversal.provider == "stripe",
                        DbCreditPurchaseReversal.provider_reversal_id.like("re_%"),
                    )
                )
            )
        )
    assert individual_count == 101
    assert persisted.refunded_amount_cents == 101
    assert persisted.reversed_credits == 118
    assert points.get_balances(user_id).paid_balance == 232


def test_refund_page_failure_rolls_back_every_financial_mutation(
    billing_settings: None,
) -> None:
    gateway = FakeBillingGateway()
    gateway.amount_total = 300
    db, user_id, points, _, service = _service(gateway=gateway)
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="core",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(service, _checkout_event(purchase)) == "processed"
    payment_intent_id = f"pi_{purchase.id}"
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        [_provider_refund(purchase, amount_cents=60)],
        [_provider_refund(purchase, amount_cents=40)],
    ]
    gateway.refund_page_error_at = 1
    event = _refund_event(
        purchase,
        amount_cents=100,
        created=1_700_002_100,
    )

    with pytest.raises(
        BillingProviderError,
        match="temporarily unavailable",
    ):
        _process(service, event)

    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 0
    assert persisted.reversed_amount_cents == 0
    assert persisted.reversed_credits == 0
    assert points.get_balances(user_id).paid_balance == 350
    with db.session() as session:
        reversal = session.scalar(
            select(DbCreditPurchaseReversal.id).where(
                DbCreditPurchaseReversal.purchase_id == purchase.id,
            )
        )
        receipt = session.get(DbStripeWebhookEvent, event["id"])
    assert reversal is None
    assert receipt is not None
    assert receipt.status == "error"


def test_inactive_refund_cannot_cover_signed_charge_refunded_total(
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
    payment_intent_id = f"pi_{purchase.id}"
    refund_id = f"re_{uuid.uuid4().hex}"
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        [
            _provider_refund(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="succeeded",
            )
        ]
    ]
    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=40,
                created=1_700_002_200,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 60

    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        [
            _provider_refund(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="failed",
            )
        ]
    ]
    event = _refund_event(
        purchase,
        amount_cents=40,
        created=1_700_002_300,
    )
    # REGRESSION: a failed/canceled object is not refunded money and therefore
    # cannot satisfy the signed Charge object's cumulative amount_refunded.
    with pytest.raises(
        BillingProviderError,
        match="incomplete active cumulative refund total",
    ):
        _process(service, event)

    assert points.get_balances(user_id).paid_balance == 60
    assert _purchase(db, purchase.id).refunded_amount_cents == 40
    with db.session() as session:
        receipt = session.get(DbStripeWebhookEvent, event["id"])
    assert receipt is not None
    assert receipt.status == "error"


def test_concurrent_charge_refund_reconciliation_is_serialized_per_payment_intent(
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
    payment_intent_id = f"pi_{purchase.id}"
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [[_provider_refund(purchase, amount_cents=100)]]
    gateway.refund_list_started = threading.Event()
    gateway.refund_list_continue = threading.Event()
    first_event = _refund_event(
        purchase,
        amount_cents=100,
        created=1_700_002_400,
    )
    second_event = _refund_event(
        purchase,
        amount_cents=100,
        created=1_700_002_401,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_process, service, first_event)
        assert gateway.refund_list_started.wait(timeout=5)
        second = executor.submit(_process, service, second_event)
        time.sleep(0.1)
        assert not second.done()
        assert gateway.refund_list_calls == [payment_intent_id]
        gateway.refund_list_continue.set()
        assert first.result(timeout=5) == "processed"
        assert second.result(timeout=5) == "processed"

    assert points.get_balances(user_id).paid_balance == 0
    with db.session() as session:
        reversal_transactions = [
            transaction
            for transaction in session.scalars(
                select(DbPointTransaction).where(
                    DbPointTransaction.reason == "stripe_reversal",
                )
            )
            if isinstance(transaction.meta, dict) and transaction.meta.get("purchase_id") == purchase.id
        ]
    assert len(reversal_transactions) == 1


def test_legacy_migration_refund_baseline_does_not_double_count_refund_object(
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
    refund_id = f"re_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"
    with db.session() as session:
        session.add(
            DbCreditPurchaseReversal(
                id=uuid.uuid4().hex,
                purchase_id=purchase.id,
                provider="legacy_migration",
                provider_reversal_id=f"legacy:0013:refund:{purchase.id}",
                provider_event_id=None,
                provider_event_created=1_700_001_750,
                kind="refund",
                amount_cents=40,
                currency=purchase.currency,
                status="legacy_refund_manual_review",
                active=True,
                created_at=1_700_001_750,
                updated_at=1_700_001_750,
            )
        )

    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=20,
                status="succeeded",
                created=1_700_001_800,
            ),
        )
        == "processed"
    )

    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 40
    assert persisted.reversed_amount_cents == 40
    assert persisted.reversed_credits == 40
    assert points.get_balances(user_id).paid_balance == 60

    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=20,
                status="failed",
                event_type="refund.failed",
                created=1_700_001_810,
            ),
        )
        == "processed"
    )
    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 40
    assert persisted.reversed_amount_cents == 40
    assert persisted.reversed_credits == 40
    assert points.get_balances(user_id).paid_balance == 60
