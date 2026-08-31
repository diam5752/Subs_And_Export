from __future__ import annotations

from backend.tests.services.billing_test_support import (
    Any,
    BillingConflictError,
    BillingConsumerRecordStore,
    BillingProviderError,
    BillingValidationError,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    FakeBillingGateway,
    StripePaymentIntentState,
    ThreadPoolExecutor,
    _checkout_event,
    _process,
    _purchase,
    _refund_event,
    _refund_object_event,
    _service,
    billing_module,
    json,
    pytest,
    replace,
    select,
    threading,
    time,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_account_deletion_preflight_keeps_paid_and_reversal_evidence(
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
    assert (
        _process(
            service,
            _refund_object_event(
                purchase,
                amount_cents=40,
                status="succeeded",
            ),
        )
        == "processed"
    )

    with db.session() as session:
        service.prepare_account_deletion(
            session=session,
            user_id=user_id,
        )

    with db.session() as session:
        retained = session.get(DbCreditPurchase, purchase.id)
        assert retained is not None
        assert retained.fulfilled_at is not None
        assert retained.checkout_url is None
        assert (
            session.scalar(
                select(DbBillingInvoice.id).where(
                    DbBillingInvoice.purchase_id == purchase.id,
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(DbCreditPurchaseReversal.id).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(DbBillingContractConfirmation.id).where(
                    DbBillingContractConfirmation.purchase_id == purchase.id,
                )
            )
            is not None
        )


def test_account_deletion_preflight_keeps_pending_withdrawal_evidence(
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
    BillingConsumerRecordStore(db=db).submit_withdrawal(
        user_id=user_id,
        purchase_id=purchase.id,
        idempotency_key=f"withdrawal-{uuid.uuid4().hex}",
        locale="el",
        withdrawal_requested=True,
        confirmed_name="Billing Customer",
        confirmation_email=f"{user_id}@example.com",
        submitted_at=1_700_000_100,
    )

    with db.session() as session:
        with pytest.raises(
            BillingConflictError,
            match="pending manual review",
        ):
            service.prepare_account_deletion(
                session=session,
                user_id=user_id,
            )

    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None
        assert (
            session.scalar(
                select(DbBillingWithdrawalRequest.id).where(
                    DbBillingWithdrawalRequest.purchase_id == purchase.id,
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(DbBillingContractConfirmation.id).where(
                    DbBillingContractConfirmation.purchase_id == purchase.id,
                )
            )
            is not None
        )


def test_misconfigured_stripe_price_session_is_expired_and_never_returned(
    billing_settings: None,
) -> None:
    gateway = FakeBillingGateway()
    gateway.amount_total = 99
    db, user_id, _, _, service = _service(gateway=gateway)

    with pytest.raises(BillingProviderError, match="Price configuration"):
        service.create_checkout(
            user_id=user_id,
            customer_email=f"{user_id}@example.com",
            package_key="starter",
            idempotency_key=f"checkout-{uuid.uuid4().hex}",
        )

    assert len(gateway.expired) == 1
    with db.session() as session:
        purchase = session.scalar(
            select(DbCreditPurchase)
            .where(DbCreditPurchase.user_id == user_id)
            .order_by(DbCreditPurchase.created_at.desc())
            .limit(1)
        )
        assert purchase is not None
        assert purchase.status == "failed"


def test_checkout_fulfillment_and_webhook_replay_credit_exactly_once(
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
    payload = _checkout_event(purchase)

    assert _process(service, payload) == "processed"
    assert _process(service, payload) == "duplicate"
    assert gateway.capture_calls == [
        (
            f"pi_{purchase.id}",
            f"gsubs-capture-{purchase.id}",
        )
    ]
    assert gateway.cancel_calls == []
    wallet = points.get_balances(user_id)
    assert wallet.paid_balance == 100
    assert wallet.promotional_balance == 0

    status = service.get_purchase_status(
        user_id=user_id,
        checkout_session_id=str(checkout.checkout_session_id),
    )
    assert status.status == "paid"
    assert status.wallet.paid_balance == 100


def test_delayed_checkout_waits_for_async_success_without_early_credit(
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

    unpaid_completion = _checkout_event(
        purchase,
        payment_status="unpaid",
        include_payment_intent=False,
    )
    assert _process(service, unpaid_completion) == "processed"
    assert _purchase(db, purchase.id).status == "awaiting_payment"
    assert points.get_balances(user_id).paid_balance == 0

    async_success = _checkout_event(
        purchase,
        event_type="checkout.session.async_payment_succeeded",
        payment_status="paid",
    )
    assert _process(service, async_success) == "processed"
    assert _purchase(db, purchase.id).status == "paid"
    assert points.get_balances(user_id).paid_balance == 100

    late_unpaid_completion = _checkout_event(
        purchase,
        payment_status="unpaid",
        include_payment_intent=False,
    )
    assert _process(service, late_unpaid_completion) == "processed"
    assert _purchase(db, purchase.id).status == "paid"
    assert points.get_balances(user_id).paid_balance == 100

    late_failure = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.async_payment_failed",
        "livemode": False,
        "data": {"object": {"id": purchase.checkout_session_id}},
    }
    assert _process(service, late_failure) == "processed"
    assert _purchase(db, purchase.id).status == "paid"
    assert points.get_balances(user_id).paid_balance == 100


def test_concurrent_identical_webhooks_are_serialized(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    payload = _checkout_event(_purchase(db, checkout.purchase_id))
    gateway.webhook_barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _process(service, payload), range(2)))

    assert sorted(results) == ["duplicate", "processed"]
    assert points.get_balances(user_id).paid_balance == 100


def test_fulfillment_and_refund_events_are_serialized_per_purchase(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: a refund arriving after PaymentIntent persistence but before
    # wallet fulfillment must not be overwritten by a late credit grant.
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    fulfillment_paused = threading.Event()
    continue_fulfillment = threading.Event()
    original_apply = points.apply_paid_purchase_once_in_session

    def delayed_apply(
        session: Any,
        user_id_arg: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> Any:
        fulfillment_paused.set()
        assert continue_fulfillment.wait(timeout=5)
        return original_apply(
            session,
            user_id_arg,
            amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
        )

    monkeypatch.setattr(
        points,
        "apply_paid_purchase_once_in_session",
        delayed_apply,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        fulfillment = executor.submit(_process, service, _checkout_event(purchase))
        assert fulfillment_paused.wait(timeout=5)
        refund = executor.submit(_process, service, _refund_event(purchase))
        time.sleep(0.1)
        assert not refund.done()
        continue_fulfillment.set()
        assert fulfillment.result(timeout=5) == "processed"
        assert refund.result(timeout=5) == "processed"

    wallet = points.get_balances(user_id)
    assert wallet.paid_balance == 0
    assert wallet.promotional_balance == 0
    assert wallet.reversal_debt == 0
    assert _purchase(db, purchase.id).status == "reversed"


def test_same_webhook_id_with_different_payload_is_rejected(
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
    event_id = f"evt_{uuid.uuid4().hex}"
    good = _checkout_event(purchase, event_id=event_id)
    bad = _checkout_event(purchase, event_id=event_id, amount_total=101)
    assert _process(service, good) == "processed"
    with pytest.raises(BillingConflictError, match="different data"):
        _process(service, bad)


def test_fulfillment_snapshot_mismatch_never_credits_wallet(
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
    with pytest.raises(Exception, match="snapshot"):
        _process(service, _checkout_event(purchase, amount_total=101))
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_capture_rejects_payment_intent_metadata_before_capture(
    billing_settings: None,
) -> None:
    # REGRESSION: Checkout metadata alone must never authorize capture when the
    # PaymentIntent is not bound to the exact same immutable purchase.
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    payment_intent_id = f"pi_{purchase.id}"
    state = gateway.payment_intent_states[payment_intent_id]
    gateway.payment_intent_states[payment_intent_id] = replace(
        state,
        metadata={
            **state.metadata,
            "purchase_id": uuid.uuid4().hex,
        },
    )

    with pytest.raises(
        BillingProviderError,
        match="does not match the authorized purchase",
    ):
        _process(service, _checkout_event(purchase))

    assert gateway.capture_calls == []
    assert gateway.cancel_calls == []
    assert points.get_balances(user_id).paid_balance == 0
    persisted = _purchase(db, purchase.id)
    assert persisted.fulfilled_at is None
    assert persisted.payment_intent_id is None


def test_manual_capture_does_not_contact_payment_intent_on_checkout_identity_mismatch(
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
    payload = json.loads(_checkout_event(purchase))
    payload["data"]["object"]["metadata"]["package_key"] = "pro"

    with pytest.raises(
        BillingValidationError,
        match="purchase snapshot",
    ):
        _process(service, payload)

    assert gateway.payment_intent_state_lookup_calls == []
    assert gateway.capture_calls == []
    assert gateway.cancel_calls == []
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_capture_rejects_automatic_payment_intent_before_capture(
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
    gateway.payment_intent_states[payment_intent_id] = replace(
        gateway.payment_intent_states[payment_intent_id],
        capture_method="automatic",
    )

    with pytest.raises(
        BillingProviderError,
        match="does not match the authorized purchase",
    ):
        _process(service, _checkout_event(purchase))

    assert gateway.capture_calls == []
    assert gateway.cancel_calls == []
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_capture_replay_after_local_failure_captures_once_and_recovers(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: Stripe can complete capture even when the following local
    # transaction fails. Replay must observe succeeded and grant exactly once.
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    payload = _checkout_event(purchase)
    original_apply = points.apply_paid_purchase_once_in_session
    failures_remaining = 1

    def fail_once(
        session: Any,
        user_id_arg: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> Any:
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("simulated local commit failure")
        return original_apply(
            session,
            user_id_arg,
            amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
        )

    monkeypatch.setattr(
        points,
        "apply_paid_purchase_once_in_session",
        fail_once,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated local commit failure",
    ):
        _process(service, payload)
    assert gateway.capture_calls == [
        (
            f"pi_{purchase.id}",
            f"gsubs-capture-{purchase.id}",
        )
    ]
    assert points.get_balances(user_id).paid_balance == 0
    assert _purchase(db, purchase.id).payment_snapshot is None

    assert _process(service, payload) == "processed"
    assert len(gateway.capture_calls) == 1
    assert points.get_balances(user_id).paid_balance == 100
    assert _purchase(db, purchase.id).status == "paid"


def test_manual_capture_reconciles_provider_cancellation_without_credit(
    billing_settings: None,
) -> None:
    # REGRESSION: an authorization canceled outside the webhook worker must
    # become a terminal local failure instead of retrying forever.
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

    assert _process(service, _checkout_event(purchase)) == "processed"

    persisted = _purchase(db, purchase.id)
    assert persisted.status == "failed"
    assert persisted.error == "Payment authorization was canceled before capture"
    assert persisted.checkout_url is None
    assert persisted.fulfilled_at is None
    assert persisted.payment_intent_id is None
    assert gateway.capture_calls == []
    assert gateway.cancel_calls == []
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_cancellation_replay_after_local_failure_cancels_once_and_recovers(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: a successful provider cancellation must remain locally
    # recoverable when persisting the terminal failed state initially fails.
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    payload = json.loads(_checkout_event(purchase))
    payload["data"]["object"]["customer_details"]["address"]["country"] = "CY"
    original_mark = service._mark_ineligible_authorization_canceled
    failures_remaining = 1

    def fail_once(purchase_id: str) -> None:
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("simulated cancellation persistence failure")
        original_mark(purchase_id)

    monkeypatch.setattr(
        service,
        "_mark_ineligible_authorization_canceled",
        fail_once,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated cancellation persistence failure",
    ):
        _process(service, payload)
    assert gateway.cancel_calls == [
        (
            f"pi_{purchase.id}",
            f"gsubs-cancel-{purchase.id}",
        )
    ]
    assert gateway.capture_calls == []
    assert _purchase(db, purchase.id).status == "checkout_created"

    assert _process(service, payload) == "processed"
    assert len(gateway.cancel_calls) == 1
    assert _purchase(db, purchase.id).status == "failed"
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_capture_response_mismatch_never_grants_credits(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user_id, points, gateway, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    original_capture = gateway.capture_authorized_payment

    def mismatched_capture(
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState:
        captured = original_capture(
            payment_intent_id,
            idempotency_key=idempotency_key,
        )
        return replace(
            captured,
            amount_received_cents=captured.amount_received_cents - 1,
        )

    monkeypatch.setattr(
        gateway,
        "capture_authorized_payment",
        mismatched_capture,
    )

    with pytest.raises(
        BillingProviderError,
        match="Captured Stripe payment amount is invalid",
    ):
        _process(service, _checkout_event(purchase))

    assert len(gateway.capture_calls) == 1
    assert gateway.cancel_calls == []
    assert points.get_balances(user_id).paid_balance == 0
    assert _purchase(db, purchase.id).payment_snapshot is None
