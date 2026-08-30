from __future__ import annotations

from backend.tests.services.billing_test_support import (
    Any,
    BillingProviderError,
    BillingValidationError,
    Database,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbStripeWebhookEvent,
    FakeBillingGateway,
    PointsStore,
    StripeRefundState,
    _checkout_event,
    _process,
    _provider_refund,
    _purchase,
    _refund_event,
    _refund_object_event,
    _service,
    _TestBillingService,
    pytest,
    select,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_recognized_checkout_rejects_invalid_session_id_before_receipt_claim(
    billing_settings: None,
) -> None:
    db, _, _, _, service = _service()
    event_id = f"evt_{uuid.uuid4().hex}"
    event = {
        "id": event_id,
        "type": "checkout.session.expired",
        "livemode": False,
        "data": {"object": {"id": "checkout_not_a_stripe_session"}},
    }

    with pytest.raises(
        BillingValidationError,
        match="Invalid Checkout Session id",
    ):
        _process(service, event)

    with db.session() as session:
        assert session.get(DbStripeWebhookEvent, event_id) is None


def _fulfilled_billing_service() -> tuple[
    Database,
    str,
    PointsStore,
    FakeBillingGateway,
    _TestBillingService,
    DbCreditPurchase,
]:
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(service, _checkout_event(purchase)) == "processed"
    return db, user_id, points, gateway, service, _purchase(db, purchase.id)


@pytest.mark.parametrize(
    ("event_type", "status", "field", "value", "error_match"),
    (
        (
            "refund.created",
            "succeeded",
            "id",
            "rf_wrong_prefix",
            "Refund object id is invalid",
        ),
        (
            "refund.created",
            "succeeded",
            "currency",
            "",
            "Reversal currency is invalid",
        ),
        (
            "refund.created",
            "succeeded",
            "amount",
            None,
            "Reversal amount is invalid",
        ),
        (
            "refund.created",
            "succeeded",
            "amount",
            "not-an-integer",
            "Reversal amount is invalid",
        ),
        (
            "refund.created",
            "unknown",
            "status",
            "unknown",
            "Refund status is invalid",
        ),
        (
            "refund.failed",
            "succeeded",
            "status",
            "succeeded",
            "Failed refund status is invalid",
        ),
        (
            "refund.created",
            "succeeded",
            "currency",
            "usd",
            "Reversal currency mismatch",
        ),
        (
            "refund.created",
            "succeeded",
            "amount",
            101,
            "Reversal amount is invalid",
        ),
    ),
)
def test_refund_object_validation_fails_closed_without_wallet_mutation(
    billing_settings: None,
    event_type: str,
    status: str,
    field: str,
    value: Any,
    error_match: str,
) -> None:
    db, user_id, points, gateway, service, purchase = _fulfilled_billing_service()
    payment_intent_id = f"pi_{purchase.id}"
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [[]]
    event = _refund_object_event(
        purchase,
        event_type=event_type,
        status=status,
        created=1_700_010_000,
    )
    event["data"]["object"][field] = value

    with pytest.raises(BillingValidationError, match=error_match):
        _process(service, event)

    assert points.get_balances(user_id).paid_balance == 100
    persisted = _purchase(db, purchase.id)
    assert persisted.status == "paid"
    assert persisted.refunded_amount_cents == 0
    with db.session() as session:
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
            is None
        )


@pytest.mark.parametrize(
    ("case", "error_match"),
    (
        ("empty", "returned no refund objects"),
        ("duplicate", "returned duplicate objects"),
        ("invalid_currency", "returned invalid data"),
        ("over_purchase_total", "exceeds the purchase amount"),
    ),
)
def test_authoritative_refund_validation_rolls_back_summary_and_wallet(
    billing_settings: None,
    case: str,
    error_match: str,
) -> None:
    db, user_id, points, gateway, service, purchase = _fulfilled_billing_service()
    payment_intent_id = f"pi_{purchase.id}"
    first = _provider_refund(
        purchase,
        refund_id=f"re_{uuid.uuid4().hex}",
        amount_cents=60,
    )
    if case == "empty":
        refunds: list[StripeRefundState] = []
    elif case == "duplicate":
        refunds = [first, first]
    elif case == "invalid_currency":
        refunds = [
            StripeRefundState(
                id=first.id,
                payment_intent_id=first.payment_intent_id,
                amount_cents=first.amount_cents,
                currency="usd",
                status=first.status,
                created=first.created,
            )
        ]
    else:
        refunds = [
            first,
            _provider_refund(
                purchase,
                amount_cents=60,
                created=first.created + 1,
            ),
        ]
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [refunds]
    event = _refund_event(
        purchase,
        amount_cents=100 if case == "over_purchase_total" else 60,
        created=1_700_010_100,
    )

    with pytest.raises(BillingProviderError, match=error_match):
        _process(service, event)

    assert points.get_balances(user_id).paid_balance == 100
    persisted = _purchase(db, purchase.id)
    assert persisted.status == "paid"
    assert persisted.refunded_amount_cents == 0
    with db.session() as session:
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
            is None
        )


def test_charge_refund_fails_closed_when_paged_objects_do_not_cover_cumulative_total(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service, purchase = _fulfilled_billing_service()
    payment_intent_id = f"pi_{purchase.id}"
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        [
            _provider_refund(
                purchase,
                amount_cents=20,
                created=1_700_010_150,
            )
        ]
    ]
    event = _refund_event(
        purchase,
        amount_cents=40,
        created=1_700_010_151,
    )

    # REGRESSION: a complete pagination pass that still accounts for less than
    # charge.amount_refunded must be retried, never accepted as a smaller clawback.
    with pytest.raises(
        BillingProviderError,
        match="incomplete active cumulative refund total",
    ):
        _process(service, event)

    assert gateway.refund_list_calls == [payment_intent_id]
    assert points.get_balances(user_id).paid_balance == 100
    persisted = _purchase(db, purchase.id)
    assert persisted.status == "paid"
    assert persisted.refunded_amount_cents == 0
    assert persisted.reversed_amount_cents == 0
    assert persisted.reversed_credits == 0
    with db.session() as session:
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
            is None
        )
        receipt = session.get(DbStripeWebhookEvent, event["id"])
    assert receipt is not None
    assert receipt.status == "error"


def test_authoritative_refund_set_cannot_omit_previously_seen_object(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service, purchase = _fulfilled_billing_service()
    payment_intent_id = f"pi_{purchase.id}"
    first = _provider_refund(
        purchase,
        amount_cents=40,
        created=1_700_010_200,
    )
    second = _provider_refund(
        purchase,
        amount_cents=30,
        created=1_700_010_201,
    )
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [
        [first, second],
    ]
    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=70,
                created=1_700_010_202,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 30

    gateway.refund_pages_by_payment_intent[payment_intent_id] = [[first]]
    with pytest.raises(
        BillingProviderError,
        match="incomplete refund set",
    ):
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=40,
                created=1_700_010_203,
            ),
        )

    assert points.get_balances(user_id).paid_balance == 30
    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 70
    with db.session() as session:
        reversals = list(
            session.scalars(
                select(DbCreditPurchaseReversal).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                    DbCreditPurchaseReversal.kind == "refund",
                )
            )
        )
    assert {
        reversal.provider_reversal_id for reversal in reversals if reversal.provider_reversal_id.startswith("re_")
    } == {
        first.id,
        second.id,
    }


def test_refund_amount_is_immutable_across_provider_updates(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service, purchase = _fulfilled_billing_service()
    payment_intent_id = f"pi_{purchase.id}"
    gateway.refund_pages_by_payment_intent[payment_intent_id] = [[]]
    refund_id = f"re_{uuid.uuid4().hex}"
    first = _refund_object_event(
        purchase,
        refund_id=refund_id,
        amount_cents=40,
        created=1_700_010_300,
    )
    assert _process(service, first) == "processed"
    assert points.get_balances(user_id).paid_balance == 60

    conflicting = _refund_object_event(
        purchase,
        refund_id=refund_id,
        amount_cents=50,
        event_type="refund.updated",
        created=1_700_010_301,
    )
    with pytest.raises(
        BillingValidationError,
        match="Refund amount conflicts with its prior state",
    ):
        _process(service, conflicting)

    assert points.get_balances(user_id).paid_balance == 60
    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 40
    with db.session() as session:
        reversal = session.scalar(
            select(DbCreditPurchaseReversal).where(
                DbCreditPurchaseReversal.provider_reversal_id == refund_id,
            )
        )
    assert reversal is not None
    assert reversal.amount_cents == 40


def test_provider_refund_id_cannot_be_reused_across_purchases(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service, first_purchase = _fulfilled_billing_service()
    second_checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    second_purchase = _purchase(db, second_checkout.purchase_id)
    assert _process(service, _checkout_event(second_purchase)) == "processed"
    shared_refund_id = f"re_{uuid.uuid4().hex}"
    for purchase in (first_purchase, second_purchase):
        gateway.refund_pages_by_payment_intent[f"pi_{purchase.id}"] = [[]]

    assert (
        _process(
            service,
            _refund_object_event(
                first_purchase,
                refund_id=shared_refund_id,
                amount_cents=40,
                created=1_700_010_400,
            ),
        )
        == "processed"
    )
    with pytest.raises(
        BillingValidationError,
        match="Reversal object conflicts with its purchase",
    ):
        _process(
            service,
            _refund_object_event(
                second_purchase,
                refund_id=shared_refund_id,
                amount_cents=40,
                created=1_700_010_401,
            ),
        )

    assert points.get_balances(user_id).paid_balance == 160
    assert _purchase(db, first_purchase.id).refunded_amount_cents == 40
    assert _purchase(db, second_purchase.id).refunded_amount_cents == 0
