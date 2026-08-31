from __future__ import annotations

from backend.tests.services.billing_test_support import (
    BillingConflictError,
    BillingProviderError,
    BillingValidationError,
    DbBillingContractConfirmation,
    DbCreditPurchase,
    FakeBillingGateway,
    IntegrityError,
    _checkout_event,
    _process,
    _purchase,
    _service,
    billing_module,
    config,
    consumer_contract_module,
    hashlib,
    json,
    new_contract_confirmation,
    public_credit_catalog,
    pytest,
    select,
    time,
    uuid,
    verify_contract_confirmation,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)


def test_public_catalog_matches_video_brackets_and_packages(
    billing_settings: None,
) -> None:
    catalog = public_credit_catalog()
    assert catalog["catalog_version"] == "2026-08-28-v2"
    assert catalog["checkout_enabled"] is True
    assert catalog["billing_country_scope"] == ["GR"]
    assert [(item["credits"], item["amount_eur_cents"]) for item in catalog["packages"]] == [
        (100, 100),
        (350, 300),
        (1200, 1000),
    ]
    assert [item["credits"] for item in catalog["video_pricing"]] == [30, 60, 100]


def test_checkout_rejects_non_greek_billing_country_before_provider_call(
    billing_settings: None,
) -> None:
    gateway = FakeBillingGateway()
    db, user_id, _, _, service = _service(gateway=gateway)

    with pytest.raises(
        BillingValidationError,
        match="available only.*Greek billing address",
    ):
        service.create_checkout(
            user_id=user_id,
            customer_email=f"{user_id}@example.com",
            package_key="starter",
            idempotency_key=f"checkout-{uuid.uuid4().hex}",
            billing_country="CY",
        )

    assert gateway.create_calls == 0
    with db.session() as session:
        assert (
            list(
                session.scalars(
                    select(DbCreditPurchase.id).where(
                        DbCreditPurchase.user_id == user_id,
                    )
                )
            )
            == []
        )


@pytest.mark.parametrize(
    ("app_env", "checkout_prefix"),
    [
        (config.AppEnv.DEV, "cs_live_"),
        (config.AppEnv.PRODUCTION, "cs_test_"),
    ],
)
def test_checkout_creation_rejects_session_id_mode_mismatch(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    app_env: config.AppEnv,
    checkout_prefix: str,
) -> None:
    monkeypatch.setattr(config.settings, "app_env", app_env)
    gateway = FakeBillingGateway()
    gateway.checkout_session_prefix = checkout_prefix
    _, user_id, _, _, service = _service(gateway=gateway)

    with pytest.raises(BillingProviderError, match="Price configuration"):
        service.create_checkout(
            user_id=user_id,
            customer_email=f"{user_id}@example.com",
            package_key="starter",
            idempotency_key=f"checkout-{uuid.uuid4().hex}",
        )

    assert len(gateway.expired) == 1


@pytest.mark.parametrize(
    ("app_env", "checkout_prefix", "event_livemode"),
    [
        (config.AppEnv.DEV, "cs_test_", True),
        (config.AppEnv.PRODUCTION, "cs_live_", False),
    ],
)
def test_webhook_rejects_event_mode_mismatch_in_both_directions(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    app_env: config.AppEnv,
    checkout_prefix: str,
    event_livemode: bool,
) -> None:
    monkeypatch.setattr(config.settings, "app_env", app_env)
    gateway = FakeBillingGateway()
    gateway.checkout_session_prefix = checkout_prefix
    db, user_id, points, _, service = _service(gateway=gateway)
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)

    with pytest.raises(BillingValidationError, match="event mode"):
        _process(
            service,
            _checkout_event(
                purchase,
                livemode=event_livemode,
            ),
        )

    assert _purchase(db, purchase.id).fulfilled_at is None
    assert points.get_balances(user_id).paid_balance == 0


@pytest.mark.parametrize(
    "event_type",
    [
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
        "charge.refunded",
        "refund.created",
        "refund.updated",
        "refund.failed",
        "charge.dispute.created",
        "charge.dispute.updated",
        "charge.dispute.funds_withdrawn",
        "charge.dispute.funds_reinstated",
        "charge.dispute.closed",
    ],
)
def test_every_recognized_webhook_requires_boolean_livemode(
    billing_settings: None,
    event_type: str,
) -> None:
    _, _, _, _, service = _service()
    object_id = "cs_test_missing_mode" if event_type.startswith("checkout.session.") else "ch_missing_mode"
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "data": {"object": {"id": object_id}},
    }

    with pytest.raises(BillingValidationError, match="event mode is invalid"):
        _process(service, event)


@pytest.mark.parametrize(
    ("app_env", "livemode", "checkout_session_id"),
    [
        (config.AppEnv.DEV, False, "cs_live_wrong_runtime"),
        (config.AppEnv.PRODUCTION, True, "cs_test_wrong_runtime"),
    ],
)
def test_checkout_webhook_rejects_session_id_mode_mismatch_in_both_directions(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    app_env: config.AppEnv,
    livemode: bool,
    checkout_session_id: str,
) -> None:
    monkeypatch.setattr(config.settings, "app_env", app_env)
    _, _, _, _, service = _service()
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.expired",
        "livemode": livemode,
        "data": {"object": {"id": checkout_session_id}},
    }

    with pytest.raises(BillingValidationError, match="Checkout Session mode"):
        _process(service, event)


def test_unknown_webhook_does_not_require_livemode(
    billing_settings: None,
) -> None:
    _, _, _, _, service = _service()
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.updated",
        "data": {"object": {"id": "cus_unknown"}},
    }

    assert _process(service, event) == "ignored"


def test_checkout_is_idempotent_and_snapshot_conflicts_are_rejected(
    billing_settings: None,
) -> None:
    db, user_id, _, gateway, service = _service()
    key = f"checkout-{uuid.uuid4().hex}"

    first = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=key,
    )
    second = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=key,
    )
    assert first == second
    assert gateway.create_calls == 1
    purchase = _purchase(db, first.purchase_id)
    assert purchase.snapshot["amount_eur_cents"] == 100
    assert purchase.snapshot["stripe_price_id"] == "price_test_starter"
    assert purchase.integration_identifier.startswith("gsubs_credits_")
    assert len(purchase.integration_identifier.rsplit("_", 1)[-1]) == 8

    with pytest.raises(BillingConflictError):
        service.create_checkout(
            user_id=user_id,
            customer_email=f"{user_id}@example.com",
            package_key="core",
            idempotency_key=key,
        )


def test_pending_checkout_fulfills_against_its_immutable_catalog_snapshot_after_deploy(
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
    original_catalog_version = str(purchase.snapshot["catalog_version"])

    monkeypatch.setattr(
        billing_module,
        "CATALOG_VERSION",
        f"{original_catalog_version}-next-deploy",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_CONTRACT_SCHEMA_VERSION",
        2,
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "CONTRACT_CONFIRMATION_DELIVERY_STATUS",
        "available_v2",
    )

    assert _process(service, _checkout_event(purchase)) == "processed"
    fulfilled = _purchase(db, purchase.id)
    with db.session() as session:
        confirmation = session.scalar(
            select(DbBillingContractConfirmation).where(
                DbBillingContractConfirmation.purchase_id == purchase.id,
            )
        )
        assert confirmation is not None
        assert confirmation.schema_version == 1
        assert confirmation.delivery_channel == "account_vault"
        assert confirmation.delivery_status == "available_approved"
        verify_contract_confirmation(
            confirmation,
            purchase=fulfilled,
        )
    assert fulfilled.fulfilled_at is not None
    assert fulfilled.snapshot["catalog_version"] == original_catalog_version
    assert points.get_balances(user_id).paid_balance == 100


def test_approved_checkout_persists_approved_contract_delivery(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        consumer_contract_module,
        "CONTRACT_CONFIRMATION_DELIVERY_STATUS",
        consumer_contract_module.APPROVED_CONTRACT_CONFIRMATION_DELIVERY_STATUS,
    )
    db, user_id, points, _, service = _service()

    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)

    assert _process(service, _checkout_event(purchase)) == "processed"
    fulfilled = _purchase(db, purchase.id)
    with db.session() as session:
        confirmation = session.scalar(
            select(DbBillingContractConfirmation).where(
                DbBillingContractConfirmation.purchase_id == purchase.id,
            )
        )
        assert confirmation is not None
        assert confirmation.delivery_channel == "account_vault"
        assert confirmation.delivery_status == "available_approved"
        verify_contract_confirmation(
            confirmation,
            purchase=fulfilled,
        )
    assert fulfilled.fulfilled_at is not None
    assert points.get_balances(user_id).paid_balance == 100


def test_database_rejects_corrupt_contract_confirmation_before_fulfillment(
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
    confirmation = new_contract_confirmation(
        purchase=purchase,
        contract_concluded_at=1_700_000_000,
        generated_at=1_700_000_001,
    )
    corrupt_confirmation = b'{"corrupt":true}\n'
    confirmation.content_bytes = corrupt_confirmation
    confirmation.content_sha256 = hashlib.sha256(
        corrupt_confirmation,
    ).hexdigest()
    with pytest.raises(
        IntegrityError,
        match="chk_billing_contract_confirmations_identity",
    ):
        with db.session() as session:
            session.add(confirmation)

    # Defense in depth starts at the database boundary: structurally invalid
    # durable evidence cannot exist and therefore cannot precede a credit grant.
    assert points.get_balances(user_id).paid_balance == 0
    persisted = _purchase(db, purchase.id)
    assert persisted.fulfilled_at is None
    assert persisted.payment_intent_id is None


def test_self_consistent_but_wrong_contract_artifact_blocks_credit_fulfillment(
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
    confirmation = new_contract_confirmation(
        purchase=purchase,
        contract_concluded_at=1_700_000_000,
        generated_at=1_700_000_001,
    )
    decoded = json.loads(confirmation.content_bytes)
    decoded["purchase"]["package_key"] = "pro"
    confirmation.content_bytes = (
        json.dumps(
            decoded,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    confirmation.content_sha256 = hashlib.sha256(
        confirmation.content_bytes,
    ).hexdigest()
    with db.session() as session:
        session.add(confirmation)

    # Recomputing the outer byte digest cannot make altered commercial fields
    # equivalent to the immutable purchase snapshot.
    with pytest.raises(
        BillingConflictError,
        match="conflicts with purchase evidence",
    ):
        _process(service, _checkout_event(purchase))

    assert points.get_balances(user_id).paid_balance == 0
    persisted = _purchase(db, purchase.id)
    assert persisted.fulfilled_at is None
    assert persisted.payment_intent_id is None


def test_unpaid_checkout_uses_short_operational_retention(
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
    assert purchase.fulfilled_at is None
    assert purchase.payment_snapshot is None
    assert purchase.financial_retention_until == purchase.created_at + 86_400


def test_account_deletion_preflight_rejects_open_checkout(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )

    with db.session() as session:
        with pytest.raises(BillingConflictError, match="payment is still open"):
            service.prepare_account_deletion(
                session=session,
                user_id=user_id,
            )


def test_account_deletion_preflight_removes_expired_terminal_unpaid_attempt(
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
    expired = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.expired",
        "livemode": False,
        "data": {"object": {"id": purchase.checkout_session_id}},
    }
    assert _process(service, expired) == "processed"
    persisted = _purchase(db, purchase.id)
    assert persisted.checkout_url is None
    assert persisted.financial_retention_until < int(time.time()) - 5

    with db.session() as session:
        service.prepare_account_deletion(
            session=session,
            user_id=user_id,
        )

    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is None


def test_account_deletion_preflight_retains_recent_terminal_unpaid_attempt(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user_id, _, _, service = _service()
    accepted_at = int(time.time())
    monkeypatch.setattr(
        service,
        "_consumer_acceptance_timestamp",
        lambda: accepted_at,
    )
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    expired = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.expired",
        "livemode": False,
        "data": {"object": {"id": purchase.checkout_session_id}},
    }
    assert _process(service, expired) == "processed"

    with db.session() as session:
        service.prepare_account_deletion(
            session=session,
            user_id=user_id,
        )

    with db.session() as session:
        retained = session.get(DbCreditPurchase, purchase.id)
        assert retained is not None
        assert retained.user_id == user_id
        assert retained.checkout_url is None
        assert retained.status == "expired"
        assert retained.financial_retention_until == accepted_at + 86_400
