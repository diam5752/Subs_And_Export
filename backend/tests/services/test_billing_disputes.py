from __future__ import annotations

from backend.tests.services.billing_test_support import (
    BillingDisabledError,
    BillingProviderError,
    BillingService,
    BillingValidationError,
    Database,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbStripeWebhookEvent,
    FakeBillingGateway,
    PointsStore,
    SecretStr,
    StripeSdkGateway,
    _checkout_event,
    _dispute_event,
    _process,
    _purchase,
    _refund_event,
    _service,
    billing_module,
    config,
    hashlib,
    hmac,
    json,
    pytest,
    select,
    time,
    uuid,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)

CONFIGURED_LIVE_KEY = "_".join(("rk", "live", "configured"))
WRONG_TEST_KEY = "_".join(("rk", "test", "wrong", "runtime"))
WRONG_LIVE_KEY = "_".join(("rk", "live", "wrong", "runtime"))
CONFIGURED_WEBHOOK_SECRET = "_".join(("whsec", "configured"))


@pytest.mark.parametrize(
    ("first_type", "first_status", "first_created", "second_type", "second_status", "second_created", "active"),
    [
        (
            "charge.dispute.created",
            "needs_response",
            1_700_002_100,
            "charge.dispute.closed",
            "won",
            1_700_002_200,
            False,
        ),
        (
            "charge.dispute.closed",
            "won",
            1_700_002_200,
            "charge.dispute.created",
            "needs_response",
            1_700_002_100,
            False,
        ),
        (
            "charge.dispute.updated",
            "needs_response",
            1_700_002_300,
            "charge.dispute.closed",
            "won",
            1_700_002_300,
            True,
        ),
        (
            "charge.dispute.closed",
            "won",
            1_700_002_300,
            "charge.dispute.updated",
            "needs_response",
            1_700_002_300,
            True,
        ),
    ],
)
def test_dispute_ordering_uses_provider_time_and_active_same_second_wins(
    billing_settings: None,
    first_type: str,
    first_status: str,
    first_created: int,
    second_type: str,
    second_status: str,
    second_created: int,
    active: bool,
) -> None:
    # REGRESSION: delivery order previously let a late dispute.created overwrite
    # a newer won state, or let a same-second won state restore credits early.
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    dispute_id = f"dp_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"

    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type=first_type,
                status=first_status,
                created=first_created,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )
    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type=second_type,
                status=second_status,
                created=second_created,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )

    wallet = points.get_balances(user_id)
    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversal = session.scalar(
            select(DbCreditPurchaseReversal).where(
                DbCreditPurchaseReversal.provider_reversal_id == dispute_id,
            )
        )

    assert reversal is not None
    assert reversal.active is active
    assert persisted.dispute_active is active
    assert persisted.reversed_credits == (100 if active else 0)
    assert wallet.paid_balance == (0 if active else 100)


def test_dispute_warning_is_inactive_until_funds_are_withdrawn(
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
    dispute_id = f"dp_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"

    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.created",
                status="warning_needs_response",
                created=1_700_002_400,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 100

    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.funds_withdrawn",
                status="warning_needs_response",
                created=1_700_002_500,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 0

    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.funds_reinstated",
                status="under_review",
                created=1_700_002_600,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 100


def test_multiple_dispute_objects_reconcile_independently(
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
    first_dispute_id = f"dp_{uuid.uuid4().hex}"
    second_dispute_id = f"dp_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"

    for offset, dispute_id in enumerate(
        (first_dispute_id, second_dispute_id),
        start=1,
    ):
        assert (
            _process(
                service,
                _dispute_event(
                    purchase,
                    event_type="charge.dispute.created",
                    status="needs_response",
                    created=1_700_002_600 + offset,
                    dispute_id=dispute_id,
                ),
            )
            == "processed"
        )
    assert points.get_balances(user_id).paid_balance == 0

    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.closed",
                status="won",
                created=1_700_002_700,
                dispute_id=first_dispute_id,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 0
    assert _purchase(db, purchase.id).dispute_active is True

    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.closed",
                status="won",
                created=1_700_002_800,
                dispute_id=second_dispute_id,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 100
    assert _purchase(db, purchase.id).dispute_active is False
    with db.session() as session:
        reversals = list(
            session.scalars(
                select(DbCreditPurchaseReversal).where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                    DbCreditPurchaseReversal.kind == "dispute",
                )
            )
        )
    assert len(reversals) == 2
    assert all(not reversal.active for reversal in reversals)


def test_refund_and_dispute_states_are_aggregated_independently(
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
    dispute_id = f"dp_{uuid.uuid4().hex}"
    assert _process(service, _checkout_event(purchase)) == "processed"
    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=40,
                created=1_700_003_100,
            ),
        )
        == "processed"
    )
    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.created",
                status="needs_response",
                created=1_700_003_200,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 0

    assert (
        _process(
            service,
            _refund_event(
                purchase,
                amount_cents=60,
                created=1_700_003_300,
            ),
        )
        == "processed"
    )
    assert points.get_balances(user_id).paid_balance == 0
    assert (
        _process(
            service,
            _dispute_event(
                purchase,
                event_type="charge.dispute.closed",
                status="won",
                created=1_700_003_400,
                dispute_id=dispute_id,
            ),
        )
        == "processed"
    )

    wallet = points.get_balances(user_id)
    persisted = _purchase(db, purchase.id)
    with db.session() as session:
        reversal_count = len(
            list(
                session.scalars(
                    select(DbCreditPurchaseReversal).where(
                        DbCreditPurchaseReversal.purchase_id == purchase.id,
                    )
                )
            )
        )
    assert reversal_count == 4
    assert (wallet.paid_balance, wallet.reversal_debt) == (40, 0)
    assert persisted.refunded_amount_cents == 60
    assert persisted.dispute_active is False
    assert persisted.reversed_amount_cents == 60
    assert persisted.reversed_credits == 60


@pytest.mark.parametrize("created", [None, True, 0, "not-a-timestamp"])
def test_reversal_event_requires_valid_provider_created_timestamp(
    billing_settings: None,
    created: object,
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
    if created is None:
        event.pop("created")
    else:
        event["created"] = created

    with pytest.raises(BillingValidationError, match="timestamp"):
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


def test_refund_reconciliation_continues_when_new_sales_are_disabled(
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
    assert points.get_balances(user_id).paid_balance == 100

    monkeypatch.setattr(config.settings, "paid_credits_enabled", False)
    assert _process(service, _refund_event(purchase)) == "processed"
    assert points.get_balances(user_id).paid_balance == 0
    assert _purchase(db, purchase.id).status == "reversed"


def test_cold_webhook_gateway_reconciles_when_new_sales_are_disabled(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user_id, points, _, checkout_service = _service()
    checkout = checkout_service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    assert _process(checkout_service, _checkout_event(purchase)) == "processed"

    cold_gateway = FakeBillingGateway()
    monkeypatch.setattr(config.settings, "paid_credits_enabled", False)
    monkeypatch.setattr(
        billing_module,
        "StripeSdkGateway",
        lambda: cold_gateway,
    )
    cold_service = BillingService(db=db, points_store=points)

    assert _process(cold_service, _refund_event(purchase)) == "processed"
    assert points.get_balances(user_id).paid_balance == 0
    assert _purchase(db, purchase.id).status == "reversed"


def test_disabled_webhook_rejects_forged_empty_secret_without_persisting_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "app_env", config.AppEnv.PRODUCTION)
    monkeypatch.setattr(config.settings, "paid_credits_enabled", False)
    monkeypatch.setattr(config.settings, "stripe_restricted_key", SecretStr(""))
    monkeypatch.setattr(config.settings, "stripe_webhook_secret", SecretStr(""))
    db = Database()
    service = BillingService(db=db, points_store=PointsStore(db=db))
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": "customer.updated",
            "livemode": True,
            "data": {"object": {"id": "cus_forged"}},
        },
        separators=(",", ":"),
    ).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        b"",
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()

    with pytest.raises(BillingDisabledError, match="not configured"):
        service.verify_and_process_webhook(
            payload=payload,
            signature=f"t={timestamp},v1={digest}",
        )

    with db.session() as session:
        assert session.get(DbStripeWebhookEvent, event_id) is None


@pytest.mark.parametrize(
    ("restricted_key", "webhook_secret"),
    [
        (" \t", CONFIGURED_WEBHOOK_SECRET),
        (CONFIGURED_LIVE_KEY, " \t"),
    ],
)
def test_disabled_webhook_rejects_whitespace_credentials(
    monkeypatch: pytest.MonkeyPatch,
    restricted_key: str,
    webhook_secret: str,
) -> None:
    monkeypatch.setattr(config.settings, "app_env", config.AppEnv.PRODUCTION)
    monkeypatch.setattr(config.settings, "paid_credits_enabled", False)
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr(restricted_key),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr(webhook_secret),
    )

    with pytest.raises(BillingDisabledError, match="not configured"):
        StripeSdkGateway()


@pytest.mark.parametrize(
    ("app_env", "restricted_key"),
    [
        (config.AppEnv.PRODUCTION, WRONG_TEST_KEY),
        (config.AppEnv.DEV, WRONG_LIVE_KEY),
    ],
)
def test_disabled_webhook_rejects_restricted_key_mode_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    app_env: config.AppEnv,
    restricted_key: str,
) -> None:
    monkeypatch.setattr(config.settings, "app_env", app_env)
    monkeypatch.setattr(config.settings, "paid_credits_enabled", False)
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr(restricted_key),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr(CONFIGURED_WEBHOOK_SECRET),
    )

    with pytest.raises(BillingDisabledError, match="not configured"):
        StripeSdkGateway()


def test_foreign_expired_checkout_is_ignored_on_shared_stripe_account(
    billing_settings: None,
) -> None:
    _, _, _, _, service = _service()
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.expired",
        "livemode": False,
        "data": {"object": {"id": "cs_test_unknown"}},
    }
    assert _process(service, event) == "ignored"


def test_foreign_completed_checkout_is_ignored_on_shared_stripe_account(
    billing_settings: None,
) -> None:
    db, _, _, _, service = _service()
    foreign_purchase_id = uuid.uuid4().hex
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "created": 1_700_003_500,
        "livemode": False,
        "data": {
            "object": {
                "id": f"cs_test_{foreign_purchase_id}",
                "payment_status": "paid",
                "status": "complete",
                "payment_intent": f"pi_{foreign_purchase_id}",
                "metadata": {
                    "purchase_id": foreign_purchase_id,
                    "integration_identifier": "mizai_credits_abcdefgh",
                },
            }
        },
    }

    assert _process(service, event) == "ignored"
    with db.session() as session:
        assert session.get(DbCreditPurchase, foreign_purchase_id) is None


def test_unknown_locally_namespaced_checkout_fails_retryably_instead_of_being_ignored(
    billing_settings: None,
) -> None:
    _, _, _, _, service = _service()
    local_purchase_id = uuid.uuid4().hex
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "created": 1_700_003_550,
        "livemode": False,
        "data": {
            "object": {
                "id": f"cs_test_{local_purchase_id}",
                "payment_status": "paid",
                "status": "complete",
                "payment_intent": f"pi_{local_purchase_id}",
                "metadata": {
                    "purchase_id": local_purchase_id,
                    "integration_identifier": "gsubs_credits_abcdefgh",
                },
            }
        },
    }

    with pytest.raises(
        BillingProviderError,
        match="Local Checkout purchase is not available yet",
    ):
        _process(service, event)
