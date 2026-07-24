"""Prepaid video-credit Checkout and replay-safe Stripe fulfillment."""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import string
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import DbCreditPurchase, DbStripeWebhookEvent
from backend.app.services import pricing
from backend.app.services.points import PointsBalance, PointsStore, make_idempotency_id

STRIPE_API_VERSION = "2026-06-24.dahlia"
CATALOG_VERSION = "2026-07-23-v1"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,63}$")
_INTEGRATION_ALPHABET = string.ascii_lowercase


class BillingError(RuntimeError):
    """Base class for safe, user-facing billing failures."""


class BillingDisabledError(BillingError):
    pass


class BillingConflictError(BillingError):
    pass


class BillingValidationError(BillingError):
    pass


class BillingProviderError(BillingError):
    pass


@dataclass(frozen=True, slots=True)
class CreditPackage:
    key: str
    credits: int
    amount_eur_cents: int
    price_id: str
    featured: bool = False


@dataclass(frozen=True, slots=True)
class StripeCheckoutSession:
    id: str
    url: str
    amount_total: int
    currency: str


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    purchase_id: str
    checkout_session_id: str | None
    checkout_url: str | None
    status: str


@dataclass(frozen=True, slots=True)
class WebhookResult:
    event_id: str
    event_type: str
    status: str


@dataclass(frozen=True, slots=True)
class PurchaseStatus:
    purchase_id: str
    package_key: str
    credits: int
    amount_eur_cents: int
    status: str
    checkout_session_id: str | None
    wallet: PointsBalance


class BillingGateway(Protocol):
    def create_checkout_session(
        self,
        *,
        price_id: str,
        user_id: str,
        customer_email: str,
        purchase_id: str,
        package_key: str,
        credits: int,
        integration_identifier: str,
        idempotency_key: str,
    ) -> StripeCheckoutSession: ...

    def expire_checkout_session(self, session_id: str) -> None: ...

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]: ...


class StripeSdkGateway:
    """Narrow Stripe SDK adapter with SDK-level retries disabled."""

    def __init__(self) -> None:
        settings.assert_paid_credits_configuration()
        if settings.stripe_restricted_key is None or settings.stripe_webhook_secret is None:
            raise BillingDisabledError("Paid credits are not configured")
        try:
            import stripe
        except ImportError as exc:  # pragma: no cover - guarded by requirements
            raise BillingProviderError("Stripe SDK is unavailable") from exc

        self._stripe = stripe
        self._webhook_secret = settings.stripe_webhook_secret.get_secret_value()
        self._client = stripe.StripeClient(
            settings.stripe_restricted_key.get_secret_value(),
            stripe_version=STRIPE_API_VERSION,
            max_network_retries=0,
        )

    def create_checkout_session(
        self,
        *,
        price_id: str,
        user_id: str,
        customer_email: str,
        purchase_id: str,
        package_key: str,
        credits: int,
        integration_identifier: str,
        idempotency_key: str,
    ) -> StripeCheckoutSession:
        metadata = {
            "purchase_id": purchase_id,
            "user_id": user_id,
            "package_key": package_key,
            "credits": str(credits),
            "integration_identifier": integration_identifier,
            "catalog_version": CATALOG_VERSION,
        }
        session = self._client.v1.checkout.sessions.create(
            {
                "mode": "payment",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": settings.stripe_success_url,
                "cancel_url": settings.stripe_cancel_url,
                "client_reference_id": user_id,
                "customer_email": customer_email,
                "metadata": metadata,
                "payment_intent_data": {"metadata": metadata},
                "expires_at": int(time.time()) + 30 * 60,
            },
            {"idempotency_key": idempotency_key},
        )
        return StripeCheckoutSession(
            id=str(session.id or ""),
            url=str(session.url or ""),
            amount_total=int(session.amount_total or 0),
            currency=str(session.currency or "").lower(),
        )

    def expire_checkout_session(self, session_id: str) -> None:
        self._client.v1.checkout.sessions.expire(
            session_id,
            {},
            {"idempotency_key": f"expire-{session_id}"},
        )

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            # Stripe's Webhook facade is not typed; normalize its output below.
            event = self._stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
                payload,
                signature,
                self._webhook_secret,
                tolerance=settings.stripe_webhook_tolerance_seconds,
            )
        except Exception as exc:
            raise BillingValidationError("Invalid Stripe webhook signature") from exc
        if hasattr(event, "to_dict"):
            return dict(event.to_dict(recursive=True))
        if isinstance(event, dict):
            return event
        raise BillingValidationError("Invalid Stripe webhook event")


def credit_packages() -> tuple[CreditPackage, ...]:
    return (
        CreditPackage(
            key="starter",
            credits=100,
            amount_eur_cents=100,
            price_id=settings.stripe_price_starter,
        ),
        CreditPackage(
            key="core",
            credits=350,
            amount_eur_cents=300,
            price_id=settings.stripe_price_core,
            featured=True,
        ),
        CreditPackage(
            key="pro",
            credits=1200,
            amount_eur_cents=1000,
            price_id=settings.stripe_price_pro,
        ),
    )


def public_credit_catalog() -> dict[str, Any]:
    packages = credit_packages()
    return {
        "catalog_version": CATALOG_VERSION,
        "currency": "eur",
        "checkout_enabled": settings.paid_credits_enabled,
        "packages": [
            {
                "key": package.key,
                "credits": package.credits,
                "amount_eur_cents": package.amount_eur_cents,
                "featured": package.featured,
            }
            for package in packages
        ],
        "video_pricing": pricing.video_credit_catalog(),
    }


class BillingService:
    def __init__(
        self,
        *,
        db: Database,
        points_store: PointsStore,
        gateway: BillingGateway | None = None,
    ) -> None:
        self.db = db
        self.points_store = points_store
        self._gateway = gateway

    def create_checkout(
        self,
        *,
        user_id: str,
        customer_email: str,
        package_key: str,
        idempotency_key: str,
    ) -> CheckoutResult:
        gateway = self._configured_gateway()
        incoming_key = self._validate_idempotency_key(idempotency_key)
        package = self._package(package_key)
        purchase = self._ensure_purchase(
            user_id=user_id,
            package=package,
            idempotency_key=incoming_key,
        )
        if purchase.status == "checkout_created" and purchase.checkout_url:
            return self._checkout_result(purchase)
        if purchase.fulfilled_at is not None:
            return self._checkout_result(purchase)
        if purchase.status not in {"creating", "checkout_created"}:
            raise BillingConflictError("This checkout request cannot be reused")

        try:
            checkout = gateway.create_checkout_session(
                price_id=str(purchase.snapshot["stripe_price_id"]),
                user_id=purchase.user_id,
                customer_email=customer_email,
                purchase_id=purchase.id,
                package_key=purchase.package_key,
                credits=purchase.credits,
                integration_identifier=purchase.integration_identifier,
                idempotency_key=f"subframe-checkout-{purchase.id}",
            )
            self._validate_checkout_session(checkout, purchase)
        except BillingError:
            self._mark_purchase_error(purchase.id, "Checkout validation failed")
            raise
        except Exception as exc:
            self._mark_purchase_error(purchase.id, f"Stripe error: {type(exc).__name__}")
            raise BillingProviderError("Stripe Checkout is temporarily unavailable") from exc

        with self.db.session() as session:
            locked = session.scalar(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.id == purchase.id)
                .with_for_update()
                .limit(1)
            )
            if locked is None:
                raise BillingProviderError("Checkout purchase record is missing")
            if locked.checkout_session_id not in {None, checkout.id}:
                raise BillingConflictError("Checkout session conflict")
            locked.checkout_session_id = checkout.id
            locked.checkout_url = checkout.url
            locked.status = "checkout_created"
            locked.error = None
            locked.updated_at = int(time.time())

        return CheckoutResult(
            purchase_id=purchase.id,
            checkout_session_id=checkout.id,
            checkout_url=checkout.url,
            status="checkout_created",
        )

    def verify_and_process_webhook(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> WebhookResult:
        gateway = self._configured_gateway()
        event = gateway.verify_webhook(payload, signature)
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if not event_id or len(event_id) > 255 or not event_type or len(event_type) > 128:
            raise BillingValidationError("Invalid Stripe event envelope")
        event_object = event.get("data", {}).get("object")
        if not isinstance(event_object, dict):
            raise BillingValidationError("Invalid Stripe event object")

        payload_hash = hashlib.sha256(payload).hexdigest()
        lock_key = int.from_bytes(
            hashlib.sha256(event_id.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        # Serialize identical deliveries for the complete processing window.
        # Receipt-row locking alone is too short because wallet mutations use
        # their own transactions.
        with self.db.session() as lock_session:
            lock_session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            purchase_id = self._event_purchase_id(
                lock_session,
                event_type=event_type,
                obj=event_object,
            )
            if purchase_id:
                purchase_lock_key = self._advisory_lock_key(
                    f"credit-purchase:{purchase_id}",
                )
                lock_session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": purchase_lock_key},
                )
            duplicate = self._claim_webhook_event(
                event_id=event_id,
                event_type=event_type,
                payload_hash=payload_hash,
            )
            if duplicate:
                return WebhookResult(
                    event_id=event_id,
                    event_type=event_type,
                    status="duplicate",
                )

            try:
                status = self._process_event(event_id, event_type, event_object)
            except Exception as exc:
                self._mark_webhook_event(
                    event_id,
                    status="error",
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                )
                raise
            self._mark_webhook_event(event_id, status=status, error=None)
            return WebhookResult(event_id=event_id, event_type=event_type, status=status)

    def get_purchase_status(
        self,
        *,
        user_id: str,
        checkout_session_id: str,
    ) -> PurchaseStatus:
        if not checkout_session_id.startswith(("cs_test_", "cs_live_")):
            raise BillingValidationError("Invalid Checkout Session id")
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase)
                .where(
                    DbCreditPurchase.user_id == user_id,
                    DbCreditPurchase.checkout_session_id == checkout_session_id,
                )
                .limit(1)
            )
        if purchase is None:
            raise BillingValidationError("Checkout purchase not found")
        return PurchaseStatus(
            purchase_id=purchase.id,
            package_key=purchase.package_key,
            credits=purchase.credits,
            amount_eur_cents=purchase.amount_eur_cents,
            status=purchase.status,
            checkout_session_id=purchase.checkout_session_id,
            wallet=self.points_store.get_balances(user_id),
        )

    def _configured_gateway(self) -> BillingGateway:
        if not settings.paid_credits_enabled:
            raise BillingDisabledError("Credit purchases are not enabled yet")
        if self._gateway is None:
            self._gateway = StripeSdkGateway()
        return self._gateway

    def _ensure_purchase(
        self,
        *,
        user_id: str,
        package: CreditPackage,
        idempotency_key: str,
    ) -> DbCreditPurchase:
        now = int(time.time())
        purchase_id = uuid.uuid4().hex
        integration_identifier = self._integration_identifier()
        snapshot = {
            "catalog_version": CATALOG_VERSION,
            "package_key": package.key,
            "credits": package.credits,
            "amount_eur_cents": package.amount_eur_cents,
            "currency": "eur",
            "stripe_price_id": package.price_id,
        }
        with self.db.session() as session:
            session.execute(
                pg_insert(DbCreditPurchase)
                .values(
                    id=purchase_id,
                    user_id=user_id,
                    provider="stripe",
                    package_key=package.key,
                    credits=package.credits,
                    amount_eur_cents=package.amount_eur_cents,
                    currency="eur",
                    idempotency_key=idempotency_key,
                    checkout_session_id=None,
                    checkout_url=None,
                    payment_intent_id=None,
                    integration_identifier=integration_identifier,
                    status="creating",
                    fulfilled_at=None,
                    refunded_amount_cents=0,
                    dispute_active=False,
                    reversed_credits=0,
                    reversal_debt_credits=0,
                    snapshot=snapshot,
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[DbCreditPurchase.idempotency_key])
            )
            purchase = session.scalar(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.idempotency_key == idempotency_key)
                .limit(1)
            )
            if purchase is None:
                raise BillingProviderError("Could not create checkout purchase")
            if (
                purchase.user_id != user_id
                or purchase.package_key != package.key
                or purchase.credits != package.credits
                or purchase.amount_eur_cents != package.amount_eur_cents
                or purchase.currency.lower() != "eur"
                or purchase.snapshot != snapshot
            ):
                raise BillingConflictError("Idempotency key was used for another purchase")
            return purchase

    def _process_event(
        self,
        event_id: str,
        event_type: str,
        obj: dict[str, Any],
    ) -> str:
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            self._fulfill_checkout(obj)
            return "processed"
        if event_type == "checkout.session.expired":
            self._expire_checkout(obj)
            return "processed"
        if event_type == "charge.refunded":
            self._apply_reversal_event(
                obj,
                event_id=event_id,
                event_type=event_type,
            )
            return "processed"
        if event_type in {
            "charge.dispute.created",
            "charge.dispute.funds_withdrawn",
            "charge.dispute.funds_reinstated",
            "charge.dispute.closed",
        }:
            self._apply_reversal_event(
                obj,
                event_id=event_id,
                event_type=event_type,
            )
            return "processed"
        return "ignored"

    def _fulfill_checkout(self, obj: dict[str, Any]) -> None:
        session_id = str(obj.get("id") or "")
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            raise BillingValidationError("Checkout metadata is missing")
        purchase_id = str(metadata.get("purchase_id") or "")
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.id == purchase_id)
                .with_for_update()
                .limit(1)
            )
            if purchase is None:
                raise BillingValidationError("Checkout purchase is unknown")
            self._validate_fulfillment_object(obj, metadata, purchase, session_id)
            if purchase.fulfilled_at is not None:
                return
            purchase.status = "fulfilling"
            purchase.payment_intent_id = self._stripe_id(obj.get("payment_intent"))
            purchase.updated_at = int(time.time())

        credits_to_grant = max(0, purchase.credits - purchase.reversed_credits)
        if credits_to_grant > 0:
            self.points_store.apply_paid_purchase_once(
                purchase.user_id,
                credits_to_grant,
                purchase_id=purchase.id,
                transaction_id=make_idempotency_id("stripe", "purchase", purchase.id),
            )

        now = int(time.time())
        with self.db.session() as session:
            locked = session.scalar(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.id == purchase.id)
                .with_for_update()
                .limit(1)
            )
            if locked is None:
                raise BillingProviderError("Checkout purchase record disappeared")
            locked.fulfilled_at = locked.fulfilled_at or now
            locked.status = self._reversal_status(locked)
            locked.error = None
            locked.updated_at = now

    def _expire_checkout(self, obj: dict[str, Any]) -> None:
        session_id = str(obj.get("id") or "")
        if not session_id:
            raise BillingValidationError("Checkout Session id is missing")
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.checkout_session_id == session_id)
                .with_for_update()
                .limit(1)
            )
            if purchase is not None and purchase.fulfilled_at is None:
                purchase.status = "expired"
                purchase.updated_at = int(time.time())

    @staticmethod
    def _event_purchase_id(
        session: Session,
        *,
        event_type: str,
        obj: dict[str, Any],
    ) -> str | None:
        """Resolve one stable purchase lock for all events affecting a payment."""
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            metadata = obj.get("metadata")
            if isinstance(metadata, dict):
                purchase_id = str(metadata.get("purchase_id") or "")
                return purchase_id if len(purchase_id) <= 32 else None
            return None

        if event_type == "checkout.session.expired":
            session_id = str(obj.get("id") or "")
            if not session_id:
                return None
            return session.scalar(
                select(DbCreditPurchase.id)
                .where(DbCreditPurchase.checkout_session_id == session_id)
                .limit(1)
            )

        if event_type in {
            "charge.refunded",
            "charge.dispute.created",
            "charge.dispute.funds_withdrawn",
            "charge.dispute.funds_reinstated",
            "charge.dispute.closed",
        }:
            payment_intent_id = BillingService._stripe_id(obj.get("payment_intent"))
            if not payment_intent_id:
                return None
            return session.scalar(
                select(DbCreditPurchase.id)
                .where(DbCreditPurchase.payment_intent_id == payment_intent_id)
                .limit(1)
            )
        return None

    @staticmethod
    def _advisory_lock_key(value: str) -> int:
        return int.from_bytes(
            hashlib.sha256(value.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )

    def _apply_reversal_event(
        self,
        obj: dict[str, Any],
        *,
        event_id: str,
        event_type: str,
    ) -> None:
        payment_intent_id = self._stripe_id(obj.get("payment_intent"))
        if not payment_intent_id:
            raise BillingValidationError("Reversal event has no PaymentIntent")
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.payment_intent_id == payment_intent_id)
                .with_for_update()
                .limit(1)
            )
            if purchase is None:
                raise BillingValidationError("Reversal purchase is unknown")

            refunded_cents = int(purchase.refunded_amount_cents or 0)
            dispute_active = bool(purchase.dispute_active)
            if event_type == "charge.refunded":
                currency = str(obj.get("currency") or "").lower()
                if currency != purchase.currency.lower():
                    raise BillingValidationError("Refund currency mismatch")
                reported = int(obj.get("amount_refunded") or 0)
                if reported < 0 or reported > purchase.amount_eur_cents:
                    raise BillingValidationError("Refund amount is invalid")
                refunded_cents = max(refunded_cents, reported)
            elif event_type in {"charge.dispute.created", "charge.dispute.funds_withdrawn"}:
                dispute_active = True
            elif event_type == "charge.dispute.funds_reinstated":
                dispute_active = False
            elif event_type == "charge.dispute.closed":
                dispute_active = str(obj.get("status") or "").lower() != "won"

            refund_credits = (
                math.ceil(purchase.credits * refunded_cents / purchase.amount_eur_cents)
                if refunded_cents > 0
                else 0
            )
            desired_reversal = purchase.credits if dispute_active else refund_credits
            current_reversal = int(purchase.reversed_credits or 0)
            fulfilled = purchase.fulfilled_at is not None
            debt_credits = min(
                desired_reversal,
                int(purchase.reversal_debt_credits or 0),
            )

            # Hold the purchase lock while applying the idempotent wallet
            # delta. Distinct refund/dispute events for one PaymentIntent then
            # cannot both calculate against the same old reversal amount.
            if fulfilled and desired_reversal > current_reversal:
                delta = desired_reversal - current_reversal
                mutation = self.points_store.reverse_paid_purchase_once(
                    purchase.user_id,
                    delta,
                    purchase_id=purchase.id,
                    transaction_id=make_idempotency_id(
                        "stripe",
                        "reverse",
                        purchase.id,
                        event_id,
                    ),
                )
                debt_credits = min(
                    desired_reversal,
                    int(purchase.reversal_debt_credits or 0)
                    + max(0, mutation.debt_delta),
                )
            elif fulfilled and desired_reversal < current_reversal:
                delta = current_reversal - desired_reversal
                self.points_store.restore_paid_reversal_once(
                    purchase.user_id,
                    delta,
                    purchase_id=purchase.id,
                    transaction_id=make_idempotency_id(
                        "stripe",
                        "restore",
                        purchase.id,
                        event_id,
                    ),
                )
                debt_credits = min(
                    desired_reversal,
                    int(purchase.reversal_debt_credits or 0),
                )

            purchase.refunded_amount_cents = refunded_cents
            purchase.dispute_active = dispute_active
            purchase.reversed_credits = desired_reversal
            purchase.reversal_debt_credits = debt_credits
            purchase.status = self._reversal_status(purchase)
            purchase.updated_at = int(time.time())

    def _claim_webhook_event(
        self,
        *,
        event_id: str,
        event_type: str,
        payload_hash: str,
    ) -> bool:
        now = int(time.time())
        with self.db.session() as session:
            session.execute(
                pg_insert(DbStripeWebhookEvent)
                .values(
                    id=event_id,
                    event_type=event_type,
                    payload_sha256=payload_hash,
                    status="processing",
                    error=None,
                    created_at=now,
                    processed_at=None,
                )
                .on_conflict_do_nothing(index_elements=[DbStripeWebhookEvent.id])
            )
            receipt = session.scalar(
                select(DbStripeWebhookEvent)
                .where(DbStripeWebhookEvent.id == event_id)
                .with_for_update()
                .limit(1)
            )
            if receipt is None:
                raise BillingProviderError("Could not persist Stripe event")
            if receipt.event_type != event_type or receipt.payload_sha256 != payload_hash:
                raise BillingConflictError("Stripe event id was replayed with different data")
            if receipt.status in {"processed", "ignored"}:
                return True
            receipt.status = "processing"
            receipt.error = None
            return False

    def _mark_webhook_event(
        self,
        event_id: str,
        *,
        status: str,
        error: str | None,
    ) -> None:
        with self.db.session() as session:
            receipt = session.get(DbStripeWebhookEvent, event_id)
            if receipt is not None:
                receipt.status = status
                receipt.error = error
                receipt.processed_at = (
                    int(time.time()) if status in {"processed", "ignored"} else None
                )

    @staticmethod
    def _validate_fulfillment_object(
        obj: dict[str, Any],
        metadata: dict[str, Any],
        purchase: DbCreditPurchase,
        session_id: str,
    ) -> None:
        expected_metadata = {
            "purchase_id": purchase.id,
            "user_id": purchase.user_id,
            "package_key": purchase.package_key,
            "credits": str(purchase.credits),
            "integration_identifier": purchase.integration_identifier,
            "catalog_version": CATALOG_VERSION,
        }
        payment_intent_id = BillingService._stripe_id(obj.get("payment_intent"))
        if (
            not session_id
            or session_id != purchase.checkout_session_id
            or not payment_intent_id.startswith("pi_")
            or str(obj.get("payment_status") or "") != "paid"
            or str(obj.get("status") or "") != "complete"
            or int(obj.get("amount_total") or 0) != purchase.amount_eur_cents
            or str(obj.get("currency") or "").lower() != purchase.currency.lower()
            or str(obj.get("client_reference_id") or "") != purchase.user_id
            or any(str(metadata.get(key) or "") != value for key, value in expected_metadata.items())
        ):
            raise BillingValidationError("Checkout fulfillment does not match purchase snapshot")

    def _validate_checkout_session(
        self,
        checkout: StripeCheckoutSession,
        purchase: DbCreditPurchase,
    ) -> None:
        parsed = urlparse(checkout.url)
        valid = (
            checkout.id.startswith(("cs_test_", "cs_live_"))
            and parsed.scheme == "https"
            and parsed.hostname == "checkout.stripe.com"
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and checkout.amount_total == purchase.amount_eur_cents
            and checkout.currency.lower() == purchase.currency.lower()
        )
        if valid:
            return
        if checkout.id.startswith(("cs_test_", "cs_live_")):
            try:
                self._configured_gateway().expire_checkout_session(checkout.id)
            except Exception:
                pass
        raise BillingProviderError("Stripe Price configuration does not match the credit catalog")

    def _mark_purchase_error(self, purchase_id: str, error: str) -> None:
        with self.db.session() as session:
            purchase = session.get(DbCreditPurchase, purchase_id)
            if purchase is not None and purchase.fulfilled_at is None:
                purchase.status = "failed"
                purchase.error = error[:500]
                purchase.updated_at = int(time.time())

    @staticmethod
    def _reversal_status(purchase: DbCreditPurchase) -> str:
        if purchase.dispute_active:
            return "disputed"
        if purchase.reversed_credits >= purchase.credits:
            return "reversed"
        if purchase.reversed_credits > 0:
            return "partially_refunded"
        return "paid" if purchase.fulfilled_at is not None else "checkout_created"

    @staticmethod
    def _checkout_result(purchase: DbCreditPurchase) -> CheckoutResult:
        return CheckoutResult(
            purchase_id=purchase.id,
            checkout_session_id=purchase.checkout_session_id,
            checkout_url=purchase.checkout_url,
            status=purchase.status,
        )

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if not _IDEMPOTENCY_RE.fullmatch(normalized):
            raise BillingValidationError("Invalid Idempotency-Key")
        return normalized

    @staticmethod
    def _package(package_key: str) -> CreditPackage:
        normalized = package_key.strip().lower()
        for package in credit_packages():
            if package.key == normalized:
                if not package.price_id.startswith("price_"):
                    raise BillingDisabledError("Credit package is not configured")
                return package
        raise BillingValidationError("Unknown credit package")

    @staticmethod
    def _integration_identifier() -> str:
        suffix = "".join(secrets.choice(_INTEGRATION_ALPHABET) for _ in range(8))
        return f"subframe_credits_{suffix}"

    @staticmethod
    def _stripe_id(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("id") or "")
        return ""
