from __future__ import annotations

import hashlib
import hmac as hmac
import json
import threading
import time as time
import uuid
from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
from dataclasses import replace as replace
from typing import Any

import pytest
import stripe as stripe
from pydantic import SecretStr as SecretStr
from sqlalchemy import select as select
from sqlalchemy.exc import IntegrityError as IntegrityError

from backend.app.core import config
from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingContractConfirmation as DbBillingContractConfirmation,
)
from backend.app.db.models import (
    DbBillingInvoice as DbBillingInvoice,
)
from backend.app.db.models import (
    DbBillingWithdrawalRequest as DbBillingWithdrawalRequest,
)
from backend.app.db.models import (
    DbCreditPurchase,
    DbUser,
)
from backend.app.db.models import (
    DbCreditPurchaseReversal as DbCreditPurchaseReversal,
)
from backend.app.db.models import (
    DbPointTransaction as DbPointTransaction,
)
from backend.app.db.models import (
    DbStripeWebhookEvent as DbStripeWebhookEvent,
)
from backend.app.db.models import (
    DbUserPoints as DbUserPoints,
)
from backend.app.services import billing as billing_module
from backend.app.services import consumer_contracts
from backend.app.services.billing import (
    BillingConflictError as BillingConflictError,
)
from backend.app.services.billing import (
    BillingDisabledError as BillingDisabledError,
)
from backend.app.services.billing import (
    BillingProviderError,
    BillingService,
    CheckoutResult,
    StripeCheckoutSession,
    StripePaymentIntentState,
    StripeRefundState,
)
from backend.app.services.billing import (
    BillingValidationError as BillingValidationError,
)
from backend.app.services.billing import (
    StripeSdkGateway as StripeSdkGateway,
)
from backend.app.services.billing import (
    public_credit_catalog as public_credit_catalog,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordStore as BillingConsumerRecordStore,
)
from backend.app.services.billing_consumer_records import (
    new_contract_confirmation as new_contract_confirmation,
)
from backend.app.services.billing_consumer_records import (
    verify_contract_confirmation as verify_contract_confirmation,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    public_consumer_contract,
)
from backend.app.services.points import PointsStore

consumer_contract_module = consumer_contracts


class FakeBillingGateway:
    def __init__(self) -> None:
        self.create_calls = 0
        self.expired: list[str] = []
        self.payment_intent_metadata: dict[str, dict[str, str]] = {}
        self.payment_intent_lookup_calls: list[str] = []
        self.payment_intent_lookup_error: Exception | None = None
        self.payment_intent_states: dict[
            str,
            StripePaymentIntentState,
        ] = {}
        self.payment_intent_state_lookup_calls: list[str] = []
        self.capture_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[tuple[str, str]] = []
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
        payment_intent_id = f"pi_{kwargs['purchase_id']}"
        metadata = {
            "purchase_id": kwargs["purchase_id"],
            "user_id": kwargs["user_id"],
            "package_key": kwargs["package_key"],
            "credits": str(kwargs["credits"]),
            "integration_identifier": kwargs["integration_identifier"],
            "catalog_version": billing_module.CATALOG_VERSION,
            "consumer_disclosure_id": kwargs["consumer_disclosure_id"],
            "consumer_disclosure_sha256": kwargs["consumer_disclosure_sha256"],
            "consumer_contract_sha256": kwargs["consumer_contract_sha256"],
            "consumer_locale": kwargs["consumer_locale"],
            "billing_country": "GR",
            "capture_policy": billing_module.MANUAL_CAPTURE_POLICY,
        }
        self.payment_intent_states[payment_intent_id] = StripePaymentIntentState(
            id=payment_intent_id,
            status="requires_capture",
            capture_method="manual",
            amount_cents=self.amount_total,
            amount_received_cents=0,
            currency=self.currency,
            metadata=metadata,
        )
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

    def retrieve_payment_intent_state(
        self,
        payment_intent_id: str,
    ) -> StripePaymentIntentState:
        self.payment_intent_state_lookup_calls.append(
            payment_intent_id,
        )
        state = self.payment_intent_states.get(payment_intent_id)
        if state is None:
            raise BillingProviderError(
                "Stripe PaymentIntent lookup is temporarily unavailable",
            )
        return state

    def capture_authorized_payment(
        self,
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState:
        state = self.retrieve_payment_intent_state(
            payment_intent_id,
        )
        if state.status == "succeeded":
            return state
        if state.status != "requires_capture":
            raise BillingProviderError(
                "Stripe payment authorization is not capturable",
            )
        self.capture_calls.append(
            (payment_intent_id, idempotency_key),
        )
        captured = StripePaymentIntentState(
            id=state.id,
            status="succeeded",
            capture_method=state.capture_method,
            amount_cents=state.amount_cents,
            amount_received_cents=state.amount_cents,
            currency=state.currency,
            metadata=dict(state.metadata),
        )
        self.payment_intent_states[payment_intent_id] = captured
        return captured

    def cancel_authorized_payment(
        self,
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState:
        state = self.retrieve_payment_intent_state(
            payment_intent_id,
        )
        if state.status == "canceled":
            return state
        if state.status != "requires_capture":
            raise BillingProviderError(
                "Stripe payment authorization is not cancelable",
            )
        self.cancel_calls.append(
            (payment_intent_id, idempotency_key),
        )
        canceled = StripePaymentIntentState(
            id=state.id,
            status="canceled",
            capture_method=state.capture_method,
            amount_cents=state.amount_cents,
            amount_received_cents=0,
            currency=state.currency,
            metadata=dict(state.metadata),
        )
        self.payment_intent_states[payment_intent_id] = canceled
        return canceled

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
                current = _charge_refund_states(
                    event,
                    obj,
                    payment_intent_id=payment_intent_id,
                    current=current,
                )
            else:
                refund = _fake_refund_state(
                    obj,
                    payment_intent_id=payment_intent_id,
                )
                current = [existing for existing in current if existing.id != refund.id]
                current.append(refund)
            self._provider_refunds[payment_intent_id] = current


def _charge_refund_states(
    event: dict[str, Any],
    obj: dict[str, Any],
    *,
    payment_intent_id: str,
    current: list[StripeRefundState],
) -> list[StripeRefundState]:
    embedded = obj.get("refunds")
    embedded_data = embedded.get("data") if isinstance(embedded, dict) else None
    if isinstance(embedded_data, list):
        return [
            _fake_refund_state(
                raw_refund,
                payment_intent_id=payment_intent_id,
            )
            for raw_refund in embedded_data
            if isinstance(raw_refund, dict)
        ]

    amount_refunded = int(obj.get("amount_refunded") or 0)
    active_total = sum(
        refund.amount_cents for refund in current if refund.status in billing_module._ACTIVE_REFUND_STATUSES
    )
    if amount_refunded <= active_total:
        return current
    try:
        refund_created = int(event.get("created") or 1)
    except (TypeError, ValueError):
        refund_created = 1
    digest = hashlib.sha256(
        (f"{event.get('id')}:{payment_intent_id}:{amount_refunded}").encode(),
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
    return current


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
        billing_country: str = "GR",
    ) -> CheckoutResult:
        return super().create_checkout(
            user_id=user_id,
            customer_email=customer_email,
            package_key=package_key,
            idempotency_key=idempotency_key,
            consumer_contract=(consumer_contract or _consumer_contract_acceptance()),
            billing_country=billing_country,
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
    payment_status: str = "unpaid",
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
        "billing_country": purchase.snapshot["billing_country"],
        "capture_policy": purchase.snapshot.get(
            "capture_policy",
            "",
        ),
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
