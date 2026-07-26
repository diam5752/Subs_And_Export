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
from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbPointTransaction,
    DbStripeWebhookEvent,
    DbUser,
    DbUserPoints,
)
from backend.app.services import billing as billing_module
from backend.app.services import consumer_contracts as consumer_contract_module
from backend.app.services.billing import (
    BillingConflictError,
    BillingDisabledError,
    BillingProviderError,
    BillingService,
    BillingValidationError,
    CheckoutResult,
    StripeCheckoutSession,
    StripeRefundState,
    StripeSdkGateway,
    public_credit_catalog,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordStore,
    new_contract_confirmation,
    verify_contract_confirmation,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    public_consumer_contract,
)
from backend.app.services.points import PointsStore


class FakeBillingGateway:
    def __init__(self) -> None:
        self.create_calls = 0
        self.expired: list[str] = []
        self.payment_intent_metadata: dict[str, dict[str, str]] = {}
        self.payment_intent_lookup_calls: list[str] = []
        self.payment_intent_lookup_error: Exception | None = None
        self.refund_pages_by_payment_intent: dict[
            str,
            list[list[StripeRefundState]],
        ] = {}
        self.refund_list_calls: list[str] = []
        self.refund_page_error_at: int | None = None
        self.refund_list_started: threading.Event | None = None
        self.refund_list_continue: threading.Event | None = None
        self._provider_refunds: dict[str, list[StripeRefundState]] = {}
        self._refund_state_lock = threading.Lock()
        self.amount_total = 100
        self.currency = "eur"
        self.checkout_session_prefix = "cs_test_"
        self.webhook_barrier: threading.Barrier | None = None

    def create_checkout_session(self, **kwargs: Any) -> StripeCheckoutSession:
        self.create_calls += 1
        return StripeCheckoutSession(
            id=f"{self.checkout_session_prefix}{kwargs['purchase_id']}",
            url=f"https://checkout.stripe.com/c/pay/{kwargs['purchase_id']}",
            amount_total=self.amount_total,
            currency=self.currency,
        )

    def expire_checkout_session(self, session_id: str) -> None:
        self.expired.append(session_id)

    def retrieve_payment_intent_metadata(
        self,
        payment_intent_id: str,
    ) -> dict[str, str]:
        self.payment_intent_lookup_calls.append(payment_intent_id)
        if self.payment_intent_lookup_error is not None:
            raise self.payment_intent_lookup_error
        return dict(self.payment_intent_metadata.get(payment_intent_id, {}))

    def list_payment_intent_refunds(
        self,
        payment_intent_id: str,
    ) -> tuple[StripeRefundState, ...]:
        self.refund_list_calls.append(payment_intent_id)
        if self.refund_list_started is not None:
            self.refund_list_started.set()
        if self.refund_list_continue is not None:
            assert self.refund_list_continue.wait(timeout=5)

        with self._refund_state_lock:
            pages = self.refund_pages_by_payment_intent.get(
                payment_intent_id,
            )
            if pages is None:
                pages = [
                    list(
                        self._provider_refunds.get(
                            payment_intent_id,
                            [],
                        )
                    )
                ]
            materialized: list[StripeRefundState] = []
            for page_index, page in enumerate(pages):
                if self.refund_page_error_at == page_index:
                    raise BillingProviderError(
                        "Stripe refund reconciliation is temporarily unavailable",
                    )
                materialized.extend(page)
            if self.refund_page_error_at == len(pages):
                raise BillingProviderError(
                    "Stripe refund reconciliation is temporarily unavailable",
                )
            return tuple(materialized)

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        assert signature == "test-signature"
        if self.webhook_barrier is not None:
            self.webhook_barrier.wait(timeout=5)
        decoded = json.loads(payload)
        assert isinstance(decoded, dict)
        self._update_provider_refund_state(decoded)
        return decoded

    def _update_provider_refund_state(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type not in {
            "charge.refunded",
            "refund.created",
            "refund.updated",
            "refund.failed",
        }:
            return
        obj = event.get("data", {}).get("object")
        if not isinstance(obj, dict):
            return
        payment_intent_id = str(obj.get("payment_intent") or "")
        if not payment_intent_id:
            return

        with self._refund_state_lock:
            if payment_intent_id in self.refund_pages_by_payment_intent:
                return
            current = list(
                self._provider_refunds.get(payment_intent_id, []),
            )
            if event_type == "charge.refunded":
                embedded = obj.get("refunds")
                embedded_data = embedded.get("data") if isinstance(embedded, dict) else None
                if isinstance(embedded_data, list):
                    current = [
                        _fake_refund_state(
                            raw_refund,
                            payment_intent_id=payment_intent_id,
                        )
                        for raw_refund in embedded_data
                        if isinstance(raw_refund, dict)
                    ]
                else:
                    amount_refunded = int(obj.get("amount_refunded") or 0)
                    active_total = sum(
                        refund.amount_cents
                        for refund in current
                        if refund.status in billing_module._ACTIVE_REFUND_STATUSES
                    )
                    if amount_refunded > active_total:
                        try:
                            refund_created = int(
                                event.get("created") or 1,
                            )
                        except (TypeError, ValueError):
                            refund_created = 1
                        digest = hashlib.sha256(
                            (f"{event.get('id')}:{payment_intent_id}:{amount_refunded}").encode()
                        ).hexdigest()
                        current.append(
                            StripeRefundState(
                                id=f"re_auto_{digest[:32]}",
                                payment_intent_id=payment_intent_id,
                                amount_cents=amount_refunded - active_total,
                                currency=str(obj.get("currency") or ""),
                                status="succeeded",
                                created=refund_created,
                            )
                        )
            else:
                refund = _fake_refund_state(
                    obj,
                    payment_intent_id=payment_intent_id,
                )
                current = [existing for existing in current if existing.id != refund.id]
                current.append(refund)
            self._provider_refunds[payment_intent_id] = current


def _fake_refund_state(
    raw_refund: dict[str, Any],
    *,
    payment_intent_id: str,
) -> StripeRefundState:
    return StripeRefundState(
        id=str(raw_refund.get("id") or ""),
        payment_intent_id=payment_intent_id,
        amount_cents=int(raw_refund.get("amount") or 0),
        currency=str(raw_refund.get("currency") or "eur"),
        status=str(raw_refund.get("status") or "succeeded"),
        created=int(raw_refund.get("created") or 1),
    )


def _consumer_contract_acceptance(
    locale: str = "el",
) -> ConsumerContractAcceptance:
    disclosure = public_consumer_contract(locale)
    return ConsumerContractAcceptance(
        catalog_version=billing_module.CATALOG_VERSION,
        disclosure_id=str(disclosure["disclosure_id"]),
        disclosure_sha256=str(disclosure["disclosure_sha256"]),
        locale=locale,  # type: ignore[arg-type]
        policy_version=str(disclosure["policy_version"]),
        terms_version=str(disclosure["terms_version"]),
        withdrawal_notice_version=str(
            disclosure["withdrawal_notice_version"],
        ),
        terms_accepted=True,
        immediate_performance_requested=True,
        withdrawal_consequences_acknowledged=True,
    )


class _TestBillingService(BillingService):
    def _consumer_acceptance_timestamp(self) -> int:
        # Financial event fixtures intentionally use a fixed provider timeline.
        return 1_699_999_999

    def create_checkout(
        self,
        *,
        user_id: str,
        customer_email: str,
        package_key: str,
        idempotency_key: str,
        consumer_contract: ConsumerContractAcceptance | None = None,
    ) -> CheckoutResult:
        return super().create_checkout(
            user_id=user_id,
            customer_email=customer_email,
            package_key=package_key,
            idempotency_key=idempotency_key,
            consumer_contract=(consumer_contract or _consumer_contract_acceptance()),
        )


@pytest.fixture
def billing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "app_env", config.AppEnv.DEV)
    monkeypatch.setattr(config.settings, "paid_credits_enabled", True)
    monkeypatch.setattr(config.settings, "consumer_policy_approved", True)
    monkeypatch.setattr(
        config.settings,
        "durable_confirmation_channel_ready",
        True,
    )
    monkeypatch.setattr(
        config.settings,
        "adjustment_workflow_ready",
        True,
    )
    monkeypatch.setattr(config.settings, "stripe_price_starter", "price_test_starter")
    monkeypatch.setattr(config.settings, "stripe_price_core", "price_test_core")
    monkeypatch.setattr(config.settings, "stripe_price_pro", "price_test_pro")
    monkeypatch.setattr(
        billing_module,
        "consumer_contract_registry_is_approved",
        lambda: True,
    )


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
) -> tuple[
    Database,
    str,
    PointsStore,
    FakeBillingGateway,
    _TestBillingService,
]:
    db = Database()
    user_id = _seed_user(db)
    points = PointsStore(db=db)
    points.ensure_account(user_id)
    resolved_gateway = gateway or FakeBillingGateway()
    service = _TestBillingService(
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
    event_type: str = "checkout.session.completed",
    created: int = 1_700_000_000,
    payment_status: str = "paid",
    amount_total: int | None = None,
    include_payment_intent: bool = True,
    livemode: bool = False,
) -> bytes:
    metadata: dict[str, Any] = {
        "purchase_id": purchase.id,
        "user_id": purchase.user_id,
        "package_key": purchase.package_key,
        "credits": str(purchase.credits),
        "integration_identifier": purchase.integration_identifier,
        "catalog_version": purchase.snapshot["catalog_version"],
    }
    consumer_contract = purchase.snapshot.get("consumer_contract")
    if isinstance(consumer_contract, dict):
        metadata.update(
            {
                "consumer_disclosure_id": consumer_contract["disclosure_id"],
                "consumer_disclosure_sha256": consumer_contract["disclosure_sha256"],
                "consumer_contract_sha256": purchase.snapshot["consumer_contract_sha256"],
                "consumer_locale": consumer_contract["locale"],
            }
        )
    checkout_object: dict[str, Any] = {
        "id": purchase.checkout_session_id,
        "payment_status": payment_status,
        "status": "complete",
        "amount_total": (purchase.amount_eur_cents if amount_total is None else amount_total),
        "currency": purchase.currency,
        "client_reference_id": purchase.user_id,
        "customer": f"cus_{purchase.id}",
        "customer_details": {
            "name": "Billing Person",
            "email": f"{purchase.user_id}@example.com",
            "address": {
                "country": "GR",
                "city": "Athens",
                "postal_code": "105 58",
                "line1": "Test Street 1",
                "line2": None,
                "state": "Attica",
            },
            "tax_ids": [],
        },
        "automatic_tax": {"enabled": False, "status": None},
        "total_details": {"amount_tax": 0},
        "metadata": metadata,
    }
    if include_payment_intent:
        checkout_object["payment_intent"] = f"pi_{purchase.id}"
    payload = {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "created": created,
        "livemode": livemode,
        "type": event_type,
        "data": {"object": checkout_object},
    }
    return json.dumps(payload, sort_keys=True).encode()


def _refund_event(
    purchase: DbCreditPurchase,
    *,
    amount_cents: int | None = None,
    created: int = 1_700_000_100,
    event_id: str | None = None,
    refunds: list[StripeRefundState] | None = None,
) -> dict[str, Any]:
    charge_object: dict[str, Any] = {
        "id": f"ch_{purchase.id}",
        "payment_intent": f"pi_{purchase.id}",
        "currency": "eur",
        "amount_refunded": (purchase.amount_eur_cents if amount_cents is None else amount_cents),
    }
    if refunds is not None:
        charge_object["refunds"] = {
            "data": [
                {
                    "id": refund.id,
                    "payment_intent": refund.payment_intent_id,
                    "amount": refund.amount_cents,
                    "currency": refund.currency,
                    "status": refund.status,
                    "created": refund.created,
                }
                for refund in refunds
            ]
        }
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "charge.refunded",
        "created": created,
        "livemode": False,
        "data": {"object": charge_object},
    }


def _refund_object_event(
    purchase: DbCreditPurchase,
    *,
    refund_id: str | None = None,
    payment_intent_id: str | None = None,
    amount_cents: int = 40,
    status: str = "succeeded",
    event_type: str = "refund.created",
    created: int = 1_700_000_100,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "created": created,
        "livemode": False,
        "data": {
            "object": {
                "id": refund_id or f"re_{uuid.uuid4().hex}",
                "payment_intent": payment_intent_id or f"pi_{purchase.id}",
                "currency": purchase.currency,
                "amount": amount_cents,
                "status": status,
            }
        },
    }


def _provider_refund(
    purchase: DbCreditPurchase,
    *,
    refund_id: str | None = None,
    amount_cents: int,
    status: str = "succeeded",
    created: int = 1_700_000_100,
) -> StripeRefundState:
    return StripeRefundState(
        id=refund_id or f"re_{uuid.uuid4().hex}",
        payment_intent_id=f"pi_{purchase.id}",
        amount_cents=amount_cents,
        currency=purchase.currency,
        status=status,
        created=created,
    )


def _dispute_event(
    purchase: DbCreditPurchase,
    *,
    event_type: str,
    status: str,
    created: int,
    dispute_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "created": created,
        "livemode": False,
        "data": {
            "object": {
                "id": dispute_id or f"dp_{purchase.id}",
                "payment_intent": f"pi_{purchase.id}",
                "amount": purchase.amount_eur_cents,
                "currency": purchase.currency,
                "status": status,
            }
        },
    }


def _process(
    service: BillingService,
    event: dict[str, Any] | bytes,
) -> str:
    payload = event if isinstance(event, bytes) else json.dumps(event, sort_keys=True).encode()
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
        assert confirmation.delivery_status == "available_pending_external_approval"
        verify_contract_confirmation(
            confirmation,
            purchase=fulfilled,
        )
    assert fulfilled.fulfilled_at is not None
    assert fulfilled.snapshot["catalog_version"] == original_catalog_version
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


def test_delayed_checkout_waits_for_async_success_without_early_credit(
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
        (" \t", "whsec_configured"),
        ("rk_live_configured", " \t"),
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
        (config.AppEnv.PRODUCTION, "rk_test_wrong_runtime"),
        (config.AppEnv.DEV, "rk_live_wrong_runtime"),
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
        SecretStr("whsec_configured"),
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
) -> None:
    db, user_id, points, _, service = _service()
    checkout = service.create_checkout(
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
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
            captured["expired_session_id"] = session_id
            captured["expire_params"] = params
            captured["expire_options"] = options
            return None

    class _PaymentIntents:
        def retrieve(self, payment_intent_id: str) -> Any:
            captured["retrieved_payment_intent_id"] = payment_intent_id
            return type(
                "PaymentIntent",
                (),
                {
                    "metadata": {
                        "purchase_id": "a" * 32,
                        "integration_identifier": "gsubs_credits_abcdefgh",
                    },
                },
            )()

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
    assert params["customer_creation"] == "always"
    assert params["billing_address_collection"] == "required"
    assert params["name_collection"] == {"individual": {"enabled": True}}
    assert params["payment_intent_data"]["receipt_email"] == "person@example.com"
    assert params["expires_at"] >= checkout_started_at + 60 * 60
    assert params["expires_at"] <= int(time.time()) + 60 * 60
    assert "price_data" not in params["line_items"][0]
    assert "payment_method_types" not in params
    assert "automatic_tax" not in params
    assert captured["options"] == {"idempotency_key": "subframe-checkout-test"}
    assert gateway.retrieve_payment_intent_metadata("pi_lookup") == {
        "purchase_id": "a" * 32,
        "integration_identifier": "gsubs_credits_abcdefgh",
    }
    assert captured["retrieved_payment_intent_id"] == "pi_lookup"
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


def test_stripe_sdk_refund_pagination_error_is_fail_closed(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config.settings,
        "stripe_restricted_key",
        SecretStr("rk_test_restricted"),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr("whsec_test_signing_secret"),
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
        SecretStr("rk_test_restricted"),
    )
    monkeypatch.setattr(
        config.settings,
        "stripe_webhook_secret",
        SecretStr("whsec_test_signing_secret"),
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
