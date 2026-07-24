from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import stripe
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core import config
from backend.app.core.database import Database
from backend.app.db.models import DbCreditPurchase, DbUser
from backend.app.services.billing import (
    BillingConflictError,
    BillingProviderError,
    BillingService,
    StripeCheckoutSession,
    StripeSdkGateway,
    public_credit_catalog,
)
from backend.app.services.points import PointsStore


class FakeBillingGateway:
    def __init__(self) -> None:
        self.create_calls = 0
        self.expired: list[str] = []
        self.amount_total = 100
        self.currency = "eur"
        self.webhook_barrier: threading.Barrier | None = None

    def create_checkout_session(self, **kwargs: Any) -> StripeCheckoutSession:
        self.create_calls += 1
        return StripeCheckoutSession(
            id=f"cs_test_{kwargs['purchase_id']}",
            url=f"https://checkout.stripe.com/c/pay/{kwargs['purchase_id']}",
            amount_total=self.amount_total,
            currency=self.currency,
        )

    def expire_checkout_session(self, session_id: str) -> None:
        self.expired.append(session_id)

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        assert signature == "test-signature"
        if self.webhook_barrier is not None:
            self.webhook_barrier.wait(timeout=5)
        return json.loads(payload)


@pytest.fixture
def billing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "paid_credits_enabled", True)
    monkeypatch.setattr(config.settings, "stripe_price_starter", "price_test_starter")
    monkeypatch.setattr(config.settings, "stripe_price_core", "price_test_core")
    monkeypatch.setattr(config.settings, "stripe_price_pro", "price_test_pro")


def _seed_user(db: Database) -> str:
    user_id = uuid.uuid4().hex
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=f"{user_id}@example.com",
                name="Billing",
                provider="local",
                password_hash="x",
                google_sub=None,
                created_at="now",
                email_verified=True,
            )
        )
    return user_id


def _service(
    *,
    gateway: FakeBillingGateway | None = None,
) -> tuple[Database, str, PointsStore, FakeBillingGateway, BillingService]:
    db = Database()
    user_id = _seed_user(db)
    points = PointsStore(db=db)
    points.ensure_account(user_id)
    resolved_gateway = gateway or FakeBillingGateway()
    service = BillingService(
        db=db,
        points_store=points,
        gateway=resolved_gateway,
    )
    return db, user_id, points, resolved_gateway, service


def _purchase(db: Database, purchase_id: str) -> DbCreditPurchase:
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        return purchase


def _checkout_event(
    purchase: DbCreditPurchase,
    *,
    event_id: str | None = None,
    amount_total: int | None = None,
) -> bytes:
    payload = {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": purchase.checkout_session_id,
                "payment_status": "paid",
                "status": "complete",
                "amount_total": amount_total or purchase.amount_eur_cents,
                "currency": purchase.currency,
                "client_reference_id": purchase.user_id,
                "payment_intent": f"pi_{purchase.id}",
                "metadata": {
                    "purchase_id": purchase.id,
                    "user_id": purchase.user_id,
                    "package_key": purchase.package_key,
                    "credits": str(purchase.credits),
                    "integration_identifier": purchase.integration_identifier,
                    "catalog_version": purchase.snapshot["catalog_version"],
                },
            }
        },
    }
    return json.dumps(payload, sort_keys=True).encode()


def _refund_event(purchase: DbCreditPurchase) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "charge.refunded",
        "data": {
            "object": {
                "id": f"ch_{purchase.id}",
                "payment_intent": f"pi_{purchase.id}",
                "currency": "eur",
                "amount_refunded": purchase.amount_eur_cents,
            }
        },
    }


def _process(
    service: BillingService,
    event: dict[str, Any] | bytes,
) -> str:
    payload = (
        event
        if isinstance(event, bytes)
        else json.dumps(event, sort_keys=True).encode()
    )
    return service.verify_and_process_webhook(
        payload=payload,
        signature="test-signature",
    ).status


def test_public_catalog_matches_video_brackets_and_packages(
    billing_settings: None,
) -> None:
    catalog = public_credit_catalog()
    assert catalog["checkout_enabled"] is True
    assert [(item["credits"], item["amount_eur_cents"]) for item in catalog["packages"]] == [
        (100, 100),
        (350, 300),
        (1200, 1000),
    ]
    assert [item["credits"] for item in catalog["video_pricing"]] == [30, 60, 100]


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
    assert purchase.integration_identifier.startswith("subframe_credits_")
    assert len(purchase.integration_identifier.rsplit("_", 1)[-1]) == 8

    with pytest.raises(BillingConflictError):
        service.create_checkout(
            user_id=user_id,
            customer_email=f"{user_id}@example.com",
            package_key="core",
            idempotency_key=key,
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
    db, user_id, points, _, service = _service()
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
    wallet = points.get_balances(user_id)
    assert wallet.paid_balance == 100
    assert wallet.promotional_balance == 500

    status = service.get_purchase_status(
        user_id=user_id,
        checkout_session_id=str(checkout.checkout_session_id),
    )
    assert status.status == "paid"
    assert status.wallet.paid_balance == 100


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
    original_apply = points.apply_paid_purchase_once

    def delayed_apply(
        user_id_arg: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> Any:
        fulfillment_paused.set()
        assert continue_fulfillment.wait(timeout=5)
        return original_apply(
            user_id_arg,
            amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
        )

    monkeypatch.setattr(points, "apply_paid_purchase_once", delayed_apply)

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
    assert wallet.promotional_balance == 500
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


def test_unknown_expired_checkout_is_a_safe_noop(
    billing_settings: None,
) -> None:
    _, _, _, _, service = _service()
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.expired",
        "data": {"object": {"id": "cs_test_unknown"}},
    }
    assert _process(service, event) == "processed"


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

    created = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "charge.dispute.created",
        "data": {
            "object": {
                "id": f"dp_{purchase.id}",
                "payment_intent": f"pi_{purchase.id}",
                "status": "needs_response",
            }
        },
    }
    _process(service, created)
    assert points.get_balances(user_id).reversal_debt == 100

    won = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "charge.dispute.closed",
        "data": {
            "object": {
                "id": f"dp_{purchase.id}",
                "payment_intent": f"pi_{purchase.id}",
                "status": "won",
            }
        },
    }
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

    def dispute_event(event_type: str, status: str) -> dict[str, Any]:
        return {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": event_type,
            "data": {
                "object": {
                    "id": f"dp_{purchase.id}",
                    "payment_intent": f"pi_{purchase.id}",
                    "status": status,
                }
            },
        }

    _process(service, dispute_event("charge.dispute.created", "needs_response"))
    assert points.get_balances(user_id).paid_balance == 0

    _process(service, dispute_event("charge.dispute.funds_reinstated", "under_review"))
    assert points.get_balances(user_id).paid_balance == 100

    _process(service, dispute_event("charge.dispute.closed", "lost"))
    wallet = points.get_balances(user_id)
    assert wallet.paid_balance == 0
    assert wallet.reversal_debt == 0
    assert _purchase(db, purchase.id).status == "disputed"


def test_stripe_sdk_gateway_disables_retries_uses_fixed_price_and_verifies_signature(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_secret = "whsec_test_signing_secret"
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr("rk_test_restricted"),
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
            return None

    class _Client:
        def __init__(self) -> None:
            self.v1 = type(
                "V1",
                (),
                {"checkout": type("Checkout", (), {"sessions": _Sessions()})()},
            )()

    def _client_factory(api_key: str, **kwargs: Any) -> _Client:
        captured["api_key_prefix"] = api_key.split("_", 2)[:2]
        captured["client_kwargs"] = kwargs
        return _Client()

    monkeypatch.setattr(stripe, "StripeClient", _client_factory)
    gateway = StripeSdkGateway()
    checkout = gateway.create_checkout_session(
        price_id="price_test_starter",
        user_id="user-1",
        customer_email="person@example.com",
        purchase_id="a" * 32,
        package_key="starter",
        credits=100,
        integration_identifier="subframe_credits_abcdefgh",
        idempotency_key="subframe-checkout-test",
    )
    assert checkout.id == "cs_test_fixed"
    assert captured["client_kwargs"] == {
        "stripe_version": "2026-06-24.dahlia",
        "max_network_retries": 0,
    }
    params = captured["params"]
    assert params["line_items"] == [{"price": "price_test_starter", "quantity": 1}]
    assert "price_data" not in params["line_items"][0]
    assert "payment_method_types" not in params
    assert "automatic_tax" not in params
    assert captured["options"] == {"idempotency_key": "subframe-checkout-test"}

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
