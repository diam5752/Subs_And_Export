from __future__ import annotations

from backend.tests.services.billing_test_support import (
    DbCreditPurchaseReversal,
    StripeRefundState,
    _checkout_event,
    _process,
    _purchase,
    _refund_event,
    _refund_object_event,
    _service,
    pytest,
    select,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_full_refund_claws_back_available_credits_and_creates_debt(
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
    points.spend(user_id, 80, reason="transcription", require_paid=True)

    assert _process(service, _refund_event(purchase)) == "processed"
    wallet = points.get_balances(user_id)
    assert wallet.paid_balance == 0
    assert wallet.reversal_debt == 80
    assert _purchase(db, purchase.id).status == "reversed"

    second = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    _process(service, _checkout_event(_purchase(db, second.purchase_id)))
    wallet = points.get_balances(user_id)
    assert wallet.reversal_debt == 0
    assert wallet.paid_balance == 20


@pytest.mark.parametrize(
    "states",
    [
        ((40, 1_700_001_200), (20, 1_700_001_100)),
        ((20, 1_700_001_100), (40, 1_700_001_200)),
        ((40, 1_700_001_200), (20, 1_700_001_200)),
        ((20, 1_700_001_200), (40, 1_700_001_200)),
    ],
)
def test_charge_refund_is_cumulative_and_order_independent(
    billing_settings: None,
    states: tuple[tuple[int, int], tuple[int, int]],
) -> None:
    # REGRESSION: cumulative charge.refunded payloads must never let an older
    # or same-second smaller snapshot restore already-refunded paid credits.
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(service, _checkout_event(purchase)) == "processed"

    for amount_cents, created in states:
        assert (
            _process(
                service,
                _refund_event(
                    purchase,
                    amount_cents=amount_cents,
                    created=created,
                ),
            )
            == "processed"
        )

    wallet = points.get_balances(user_id)
    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversals = list(
            session.scalars(
                select(DbCreditPurchaseReversal).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
        )

    assert (wallet.paid_balance, wallet.reversal_debt) == (60, 0)
    assert persisted.refunded_amount_cents == 40
    assert persisted.reversed_amount_cents == 40
    assert persisted.reversed_credits == 40
    individual_refunds = [reversal for reversal in reversals if reversal.provider_reversal_id.startswith("re_")]
    summaries = [reversal for reversal in reversals if reversal.provider_reversal_id.startswith("ch_")]
    assert sum(reversal.amount_cents for reversal in individual_refunds if reversal.active) == 40
    assert len(summaries) == 1
    assert (
        summaries[0].kind,
        summaries[0].amount_cents,
        summaries[0].active,
    ) == (
        "refund",
        40,
        True,
    )


def test_two_partial_refund_objects_reconcile_and_failed_refund_restores_exactly(
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
    first_refund_id = f"re_{uuid.uuid4().hex}"
    second_refund_id = f"re_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"

    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=first_refund_id,
                amount_cents=30,
                status="succeeded",
                created=1_700_001_300,
            ),
        )
        == "processed"
    )
    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=second_refund_id,
                amount_cents=20,
                status="pending",
                created=1_700_001_400,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 50
    assert _purchase(db, purchase.id).refunded_amount_cents == 50

    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=second_refund_id,
                amount_cents=20,
                status="failed",
                event_type="refund.failed",
                created=1_700_001_500,
            ),
        )
        == "processed"
    )

    wallet = points.get_balances(user_id)
    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversals = list(
            session.scalars(
                select(DbCreditPurchaseReversal)
                .where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                    DbCreditPurchaseReversal.kind == "refund",
                )
                .order_by(DbCreditPurchaseReversal.provider_reversal_id)
            )
        )
    assert wallet.paid_balance == 70
    assert persisted.refunded_amount_cents == 30
    assert persisted.reversed_amount_cents == 30
    reversal_states = {
        item.provider_reversal_id: (
            item.amount_cents,
            item.status,
            item.active,
        )
        for item in reversals
    }
    assert reversal_states == {
        first_refund_id: (30, "succeeded", True),
        second_refund_id: (20, "failed", False),
    }


def test_refund_requires_action_is_active_until_canceled(
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

    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="requires_action",
                event_type="refund.created",
                created=1_700_001_510,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 60

    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                refund_id=refund_id,
                amount_cents=40,
                status="canceled",
                event_type="refund.updated",
                created=1_700_001_520,
            ),
        )
        == "processed"
    )
    persisted = _purchase(db, purchase.id)
    assert persisted.refunded_amount_cents == 0
    assert persisted.reversed_credits == 0
    assert points.get_balances(user_id).paid_balance == 100


@pytest.mark.parametrize(
    "states",
    [
        (("pending", "refund.created"), ("failed", "refund.failed")),
        (("failed", "refund.failed"), ("pending", "refund.created")),
        (("succeeded", "refund.created"), ("canceled", "refund.updated")),
        (("canceled", "refund.updated"), ("succeeded", "refund.created")),
    ],
)
def test_refund_terminal_state_wins_same_second_in_any_delivery_order(
    billing_settings: None,
    states: tuple[tuple[str, str], tuple[str, str]],
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

    for status, event_type in states:
        assert (
            _process(
                service,
                _refund_object_event(
                    purchase,
                    refund_id=refund_id,
                    amount_cents=40,
                    status=status,
                    event_type=event_type,
                    created=1_700_001_600,
                ),
            )
            == "processed"
        )

    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversal = session.scalar(
            select(DbCreditPurchaseReversal).where(
                DbCreditPurchaseReversal.provider_reversal_id == refund_id,
            )
        )
    assert reversal is not None
    assert reversal.status in {"failed", "canceled"}
    assert reversal.active is False
    assert persisted.refunded_amount_cents == 0
    assert persisted.reversed_amount_cents == 0
    assert points.get_balances(user_id).paid_balance == 100


@pytest.mark.parametrize("terminal_first", [True, False])
def test_refund_older_active_state_cannot_overwrite_newer_terminal_state(
    billing_settings: None,
    terminal_first: bool,
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
    active = _refund_object_event(
        purchase,
        refund_id=refund_id,
        amount_cents=40,
        status="pending",
        event_type="refund.created",
        created=1_700_001_610,
    )
    terminal = _refund_object_event(
        purchase,
        refund_id=refund_id,
        amount_cents=40,
        status="failed",
        event_type="refund.failed",
        created=1_700_001_620,
    )

    for event in (terminal, active) if terminal_first else (active, terminal):
        assert _process(service, event) == "processed"

    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversal = session.scalar(
            select(DbCreditPurchaseReversal).where(
                DbCreditPurchaseReversal.provider_reversal_id == refund_id,
            )
        )
    assert reversal is not None
    assert (reversal.status, reversal.active) == ("failed", False)
    assert persisted.refunded_amount_cents == 0
    assert persisted.reversed_credits == 0
    assert points.get_balances(user_id).paid_balance == 100


@pytest.mark.parametrize("summary_first", [True, False])
def test_charge_refund_summary_does_not_double_count_individual_refund(
    billing_settings: None,
    summary_first: bool,
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
    first_refund_id = f"re_{uuid.uuid4().hex}"
    second_refund_id = f"re_{uuid.uuid4().hex}"
    refund_states = [
        StripeRefundState(
            id=first_refund_id,
            payment_intent_id=f"pi_{purchase.id}",
            amount_cents=40,
            currency=purchase.currency,
            status="succeeded",
            created=1_700_001_700,
        ),
        StripeRefundState(
            id=second_refund_id,
            payment_intent_id=f"pi_{purchase.id}",
            amount_cents=30,
            currency=purchase.currency,
            status="succeeded",
            created=1_700_001_700,
        ),
    ]
    summary = _refund_event(
        purchase,
        amount_cents=70,
        created=1_700_001_700,
        refunds=refund_states,
    )
    individuals = (
        _refund_object_event(
            purchase,
            refund_id=first_refund_id,
            amount_cents=40,
            status="succeeded",
            created=1_700_001_700,
        ),
        _refund_object_event(
            purchase,
            refund_id=second_refund_id,
            amount_cents=30,
            status="succeeded",
            created=1_700_001_700,
        ),
    )

    events = (summary, *individuals) if summary_first else (*individuals, summary)
    for event in events:
        assert _process(service, event) == "processed"

    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversals = list(
            session.scalars(
                select(DbCreditPurchaseReversal).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                    DbCreditPurchaseReversal.kind == "refund",
                )
            )
        )
    assert len(reversals) == 3
    assert persisted.refunded_amount_cents == 70
    assert persisted.reversed_amount_cents == 70
    assert persisted.reversed_credits == 70
    assert points.get_balances(user_id).paid_balance == 30
