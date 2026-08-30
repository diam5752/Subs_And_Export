from __future__ import annotations

from backend.tests.services.billing_test_support import (
    Any,
    BillingProviderError,
    SecretStr,
    StripeRefundState,
    StripeSdkGateway,
    _consumer_contract_acceptance,
    billing_module,
    config,
    hashlib,
    hmac,
    json,
    pytest,
    stripe,
    time,
)

pytest_plugins = ("backend.tests.services.billing_test_support",)

TEST_RESTRICTED_KEY = "_".join(("rk", "test", "restricted"))
TEST_WEBHOOK_SECRET = "_".join(("whsec", "test", "signing", "secret"))


def test_stripe_sdk_gateway_disables_retries_uses_fixed_price_and_verifies_signature(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_secret = TEST_WEBHOOK_SECRET
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr(TEST_RESTRICTED_KEY),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr(webhook_secret),
    )
    captured: dict[str, Any] = {}

    class _Sessions:
        def create(
            self,
            params: dict[str, Any],
            options: dict[str, Any],
        ) -> Any:
            captured["params"] = params
            captured["options"] = options
            return type(
                "Session",
                (),
                {
                    "id": "cs_test_fixed",
                    "url": "https://checkout.stripe.com/c/pay/fixed",
                    "amount_total": 100,
                    "currency": "eur",
                },
            )()

        def expire(
            self,
            session_id: str,
            params: dict[str, Any],
            options: dict[str, Any],
        ) -> Any:
            captured["expired_session_id"] = session_id
            captured["expire_params"] = params
            captured["expire_options"] = options
            return None

    class _PaymentIntents:
        def retrieve(
            self,
            payment_intent_id: str,
            params: dict[str, Any] | None = None,
            options: dict[str, Any] | None = None,
        ) -> Any:
            captured.setdefault(
                "retrieved_payment_intent_ids",
                [],
            ).append(payment_intent_id)
            return type(
                "PaymentIntent",
                (),
                {
                    "id": payment_intent_id,
                    "status": "requires_capture",
                    "capture_method": "manual",
                    "amount": 100,
                    "amount_received": 0,
                    "currency": "eur",
                    "metadata": {
                        "purchase_id": "a" * 32,
                        "integration_identifier": "gsubs_credits_abcdefgh",
                    },
                },
            )()

        def capture(
            self,
            payment_intent_id: str,
            params: dict[str, Any],
            options: dict[str, Any],
        ) -> Any:
            captured["captured_payment_intent_id"] = payment_intent_id
            captured["capture_params"] = params
            captured["capture_options"] = options
            return {
                "id": payment_intent_id,
                "status": "succeeded",
                "capture_method": "manual",
                "amount": 100,
                "amount_received": 100,
                "currency": "eur",
                "metadata": {
                    "purchase_id": "a" * 32,
                    "integration_identifier": "gsubs_credits_abcdefgh",
                },
            }

        def cancel(
            self,
            payment_intent_id: str,
            params: dict[str, Any],
            options: dict[str, Any],
        ) -> Any:
            captured["canceled_payment_intent_id"] = payment_intent_id
            captured["cancel_params"] = params
            captured["cancel_options"] = options
            return {
                "id": payment_intent_id,
                "status": "canceled",
                "capture_method": "manual",
                "amount": 100,
                "amount_received": 0,
                "currency": "eur",
                "metadata": {
                    "purchase_id": "a" * 32,
                    "integration_identifier": "gsubs_credits_abcdefgh",
                },
            }

    class _RefundPage:
        def auto_paging_iter(self) -> Any:
            captured["refund_auto_paging_called"] = True
            for index in range(101):
                yield {
                    "id": f"re_{index:032d}",
                    "payment_intent": "pi_lookup",
                    "amount": 1,
                    "currency": "eur",
                    "status": "succeeded",
                    "created": 1_700_000_000 + index,
                }

    class _Refunds:
        def list(self, params: dict[str, Any]) -> _RefundPage:
            captured["refund_list_params"] = params
            return _RefundPage()

    class _Client:
        def __init__(self) -> None:
            self.v1 = type(
                "V1",
                (),
                {
                    "checkout": type("Checkout", (), {"sessions": _Sessions()})(),
                    "payment_intents": _PaymentIntents(),
                    "refunds": _Refunds(),
                },
            )()

    def _client_factory(api_key: str, **kwargs: Any) -> _Client:
        captured["api_key_prefix"] = api_key.split("_", 2)[:2]
        captured["client_kwargs"] = kwargs
        return _Client()

    monkeypatch.setattr(stripe, "StripeClient", _client_factory)
    gateway = StripeSdkGateway()
    consumer_acceptance = _consumer_contract_acceptance()
    checkout_started_at = int(time.time())
    checkout = gateway.create_checkout_session(
        price_id="price_test_starter",
        user_id="user-1",
        customer_email="person@example.com",
        purchase_id="a" * 32,
        package_key="starter",
        credits=100,
        integration_identifier="gsubs_credits_abcdefgh",
        consumer_disclosure_id=consumer_acceptance.disclosure_id,
        consumer_disclosure_sha256=consumer_acceptance.disclosure_sha256,
        consumer_contract_sha256="f" * 64,
        consumer_locale=consumer_acceptance.locale,
        idempotency_key="subframe-checkout-test",
    )
    assert checkout.id == "cs_test_fixed"
    assert captured["client_kwargs"] == {
        "stripe_version": "2026-06-24.dahlia",
        "base_addresses": {"api": "https://api.stripe.com"},
        "max_network_retries": 0,
    }
    params = captured["params"]
    assert params["line_items"] == [{"price": "price_test_starter", "quantity": 1}]
    # REGRESSION: API 2026-03-25+ requires this as a first-class Checkout field,
    # not only as duplicated metadata.
    assert params["integration_identifier"] == "gsubs_credits_abcdefgh"
    assert params["metadata"]["consumer_disclosure_id"] == (consumer_acceptance.disclosure_id)
    assert params["metadata"]["consumer_disclosure_sha256"] == (consumer_acceptance.disclosure_sha256)
    assert params["metadata"]["consumer_contract_sha256"] == "f" * 64
    assert params["metadata"]["consumer_locale"] == consumer_acceptance.locale
    assert params["metadata"]["billing_country"] == "GR"
    assert params["metadata"]["capture_policy"] == billing_module.MANUAL_CAPTURE_POLICY
    assert params["customer_creation"] == "always"
    assert params["billing_address_collection"] == "required"
    assert params["name_collection"] == {"individual": {"enabled": True}}
    # REGRESSION: the hosted Checkout page is the actual payment step, so its
    # final action must use Stripe's explicit purchase/payment submit label.
    assert params["submit_type"] == "pay"
    # REGRESSION: Stripe must apply dynamic eligibility filtering instead of
    # forcing an unsupported method into a manual-capture Checkout Session.
    assert "payment_method_types" not in params
    assert params["payment_intent_data"]["capture_method"] == "manual"
    assert params["payment_intent_data"]["receipt_email"] == "person@example.com"
    assert params["payment_intent_data"]["statement_descriptor_suffix"] == "GSUBS"
    assert params["expires_at"] >= checkout_started_at + 60 * 60
    assert params["expires_at"] <= int(time.time()) + 60 * 60
    assert "price_data" not in params["line_items"][0]
    assert "automatic_tax" not in params
    assert captured["options"] == {"idempotency_key": "subframe-checkout-test"}
    assert gateway.retrieve_payment_intent_metadata("pi_lookup") == {
        "purchase_id": "a" * 32,
        "integration_identifier": "gsubs_credits_abcdefgh",
    }
    assert captured["retrieved_payment_intent_ids"] == ["pi_lookup"]
    captured_state = gateway.capture_authorized_payment(
        "pi_capture",
        idempotency_key="gsubs-capture-test",
    )
    assert captured_state.status == "succeeded"
    assert captured["captured_payment_intent_id"] == "pi_capture"
    assert captured["capture_params"] == {}
    assert captured["capture_options"] == {
        "idempotency_key": "gsubs-capture-test",
    }
    canceled_state = gateway.cancel_authorized_payment(
        "pi_cancel",
        idempotency_key="gsubs-cancel-test",
    )
    assert canceled_state.status == "canceled"
    assert captured["canceled_payment_intent_id"] == "pi_cancel"
    assert captured["cancel_params"] == {
        "cancellation_reason": "abandoned",
    }
    assert captured["cancel_options"] == {
        "idempotency_key": "gsubs-cancel-test",
    }
    refunds = gateway.list_payment_intent_refunds("pi_lookup")
    assert len(refunds) == 101
    assert refunds[0].payment_intent_id == "pi_lookup"
    assert captured["refund_list_params"] == {
        "payment_intent": "pi_lookup",
        "limit": 100,
    }
    assert captured["refund_auto_paging_called"] is True
    gateway.expire_checkout_session("cs_test_expire")
    assert captured["expired_session_id"] == "cs_test_expire"
    assert captured["expire_params"] == {}
    assert captured["expire_options"] == {
        "idempotency_key": "expire-cs_test_expire",
    }

    payload = json.dumps(
        {
            "id": "evt_signature_test",
            "object": "event",
            "type": "test.event",
            "data": {"object": {}},
        },
        separators=(",", ":"),
    ).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        webhook_secret.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    event = gateway.verify_webhook(payload, f"t={timestamp},v1={digest}")
    assert event["id"] == "evt_signature_test"

    with pytest.raises(Exception, match="signature"):
        gateway.verify_webhook(payload, f"t={timestamp},v1={'0' * 64}")


def test_stripe_sdk_payment_intent_write_probe_accepts_missing_resource(
    billing_settings: None,
) -> None:
    captured: dict[str, Any] = {}

    class _PaymentIntents:
        def capture(
            self,
            payment_intent_id: str,
            params: dict[str, Any],
            options: dict[str, Any],
        ) -> Any:
            captured["payment_intent_id"] = payment_intent_id
            captured["params"] = params
            captured["options"] = options
            raise stripe.InvalidRequestError(
                "No such payment_intent",
                param="id",
                code="resource_missing",
                http_status=404,
            )

    gateway = object.__new__(StripeSdkGateway)
    gateway._stripe = stripe
    gateway._client = type(
        "Client",
        (),
        {
            "v1": type(
                "V1",
                (),
                {"payment_intents": _PaymentIntents()},
            )(),
        },
    )()

    gateway.assert_payment_intent_write_access()

    assert captured == {
        "payment_intent_id": "pi_gsubs_permission_probe_absent",
        "params": {},
        "options": {
            "idempotency_key": "gsubs-permission-probe-payment-intent-write-v1",
        },
    }


def test_stripe_sdk_payment_intent_write_probe_rejects_permission_error(
    billing_settings: None,
) -> None:
    class _PaymentIntents:
        def capture(
            self,
            payment_intent_id: str,
            params: dict[str, Any],
            options: dict[str, Any],
        ) -> Any:
            raise stripe.PermissionError(
                "The provided key does not have the required permissions",
                code="permission_denied",
                http_status=403,
            )

    gateway = object.__new__(StripeSdkGateway)
    gateway._stripe = stripe
    gateway._client = type(
        "Client",
        (),
        {
            "v1": type(
                "V1",
                (),
                {"payment_intents": _PaymentIntents()},
            )(),
        },
    )()

    with pytest.raises(
        billing_module.BillingDisabledError,
        match="Payment Intents Write",
    ):
        gateway.assert_payment_intent_write_access()


def test_stripe_sdk_refund_pagination_error_is_fail_closed(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr(TEST_RESTRICTED_KEY),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr(TEST_WEBHOOK_SECRET),
    )

    class _RefundPage:
        def auto_paging_iter(self) -> Any:
            yield {
                "id": f"re_{'1' * 32}",
                "payment_intent": "pi_lookup",
                "amount": 40,
                "currency": "eur",
                "status": "succeeded",
                "created": 1_700_000_000,
            }
            raise RuntimeError("second Stripe page unavailable")

    class _Refunds:
        def list(self, params: dict[str, Any]) -> _RefundPage:
            assert params == {
                "payment_intent": "pi_lookup",
                "limit": 100,
            }
            return _RefundPage()

    class _Client:
        def __init__(self) -> None:
            self.v1 = type("V1", (), {"refunds": _Refunds()})()

    monkeypatch.setattr(
        stripe,
        "StripeClient",
        lambda *args, **kwargs: _Client(),
    )
    gateway = StripeSdkGateway()

    with pytest.raises(
        BillingProviderError,
        match="refund reconciliation is temporarily unavailable",
    ):
        gateway.list_payment_intent_refunds("pi_lookup")


def _stripe_sdk_gateway_with_refunds(
    monkeypatch: pytest.MonkeyPatch,
    raw_refunds: list[Any],
) -> StripeSdkGateway:
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr(TEST_RESTRICTED_KEY),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr(TEST_WEBHOOK_SECRET),
    )

    class _RefundPage:
        def auto_paging_iter(self) -> Any:
            yield from raw_refunds

    class _Refunds:
        def list(self, params: dict[str, Any]) -> _RefundPage:
            assert params == {
                "payment_intent": "pi_lookup",
                "limit": 100,
            }
            return _RefundPage()

    class _Client:
        def __init__(self) -> None:
            self.v1 = type("V1", (), {"refunds": _Refunds()})()

    def _client_factory(*args: Any, **kwargs: Any) -> _Client:
        return _Client()

    monkeypatch.setattr(stripe, "StripeClient", _client_factory)
    return StripeSdkGateway()


def test_stripe_sdk_refund_normalization_accepts_stripe_like_objects(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DictLikeRefund:
        def to_dict(self) -> dict[str, Any]:
            return {
                "id": f"re_{'1' * 32}",
                "payment_intent": "pi_lookup",
                "amount": 40,
                "currency": " EUR ",
                "status": " SUCCEEDED ",
                "created": 1_700_000_000,
            }

    class _AttributeRefund:
        id = f"re_{'2' * 32}"
        payment_intent = "pi_lookup"
        amount = 60
        currency = "eur"
        status = "pending"
        created = 1_700_000_001

    gateway = _stripe_sdk_gateway_with_refunds(
        monkeypatch,
        [_DictLikeRefund(), _AttributeRefund()],
    )

    assert gateway.list_payment_intent_refunds("pi_lookup") == (
        StripeRefundState(
            id=f"re_{'1' * 32}",
            payment_intent_id="pi_lookup",
            amount_cents=40,
            currency="eur",
            status="succeeded",
            created=1_700_000_000,
        ),
        StripeRefundState(
            id=f"re_{'2' * 32}",
            payment_intent_id="pi_lookup",
            amount_cents=60,
            currency="eur",
            status="pending",
            created=1_700_000_001,
        ),
    )


@pytest.mark.parametrize(
    "invalid_fields",
    (
        {"amount": True},
        {"created": False},
        {"amount": "not-an-integer"},
        {"created": "not-a-timestamp"},
        {"id": "rf_wrong_prefix"},
        {"payment_intent": "pi_other"},
        {"amount": 0},
        {"currency": ""},
        {"currency": "currency-too-long"},
        {"status": "unknown"},
        {"created": 0},
    ),
)
def test_stripe_sdk_rejects_malformed_refund_objects(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    invalid_fields: dict[str, Any],
) -> None:
    raw_refund: dict[str, Any] = {
        "id": f"re_{'1' * 32}",
        "payment_intent": "pi_lookup",
        "amount": 40,
        "currency": "eur",
        "status": "succeeded",
        "created": 1_700_000_000,
    }
    raw_refund.update(invalid_fields)
    gateway = _stripe_sdk_gateway_with_refunds(
        monkeypatch,
        [raw_refund],
    )

    with pytest.raises(
        BillingProviderError,
        match="refund reconciliation returned invalid data",
    ):
        gateway.list_payment_intent_refunds("pi_lookup")


def test_stripe_sdk_rejects_duplicate_refund_objects(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_refund = {
        "id": f"re_{'1' * 32}",
        "payment_intent": "pi_lookup",
        "amount": 40,
        "currency": "eur",
        "status": "succeeded",
        "created": 1_700_000_000,
    }
    gateway = _stripe_sdk_gateway_with_refunds(
        monkeypatch,
        [raw_refund, dict(raw_refund)],
    )

    with pytest.raises(
        BillingProviderError,
        match="duplicate objects",
    ):
        gateway.list_payment_intent_refunds("pi_lookup")
