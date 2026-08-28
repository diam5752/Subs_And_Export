"""Prepaid video-credit Checkout and replay-safe Stripe fulfillment."""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import string
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbStripeWebhookEvent,
    DbUser,
)
from backend.app.services import pricing
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordConflictError,
    BillingConsumerRecordValidationError,
    new_contract_confirmation,
    verify_contract_confirmation,
)
from backend.app.services.billing_records import (
    GREEK_B2C_BILLING_COUNTRY,
    MANUAL_CAPTURE_POLICY,
    CheckoutAccountingIneligibleError,
    PaymentCaptureEvidence,
    build_paid_financial_record,
    new_pending_invoice,
    validate_checkout_accounting_eligibility,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    ConsumerContractValidationError,
    build_consumer_contract_snapshot,
    consumer_contract_registry_is_approved,
    consumer_contract_snapshot_sha256,
    public_consumer_contract,
)
from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)
from backend.app.services.points import PointsBalance, PointsStore, make_idempotency_id

STRIPE_API_VERSION = "2026-06-24.dahlia"
CATALOG_VERSION = "2026-08-28-v2"
UNPAID_PURCHASE_RETENTION_SECONDS = 24 * 60 * 60
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,63}$")
_INTEGRATION_ALPHABET = string.ascii_lowercase
_LOCAL_INTEGRATION_RE = re.compile(r"^gsubs_credits_[a-z]{8}$")
_PURCHASE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CHECKOUT_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
    }
)
_REFUND_OBJECT_EVENT_TYPES = frozenset(
    {
        "refund.created",
        "refund.updated",
        "refund.failed",
    }
)
_REVERSAL_EVENT_TYPES = frozenset(
    {
        "charge.refunded",
        *_REFUND_OBJECT_EVENT_TYPES,
        "charge.dispute.created",
        "charge.dispute.updated",
        "charge.dispute.funds_withdrawn",
        "charge.dispute.funds_reinstated",
        "charge.dispute.closed",
    }
)
_RECOGNIZED_EVENT_TYPES = _CHECKOUT_EVENT_TYPES | _REVERSAL_EVENT_TYPES
_ACTIVE_REFUND_STATUSES = frozenset(
    {
        "pending",
        "requires_action",
        "succeeded",
    }
)
_INACTIVE_REFUND_STATUSES = frozenset({"failed", "canceled"})
_REFUND_STATUS_RANK = {
    "pending": 0,
    "requires_action": 0,
    "succeeded": 1,
    "failed": 2,
    "canceled": 2,
}
_CHARGE_REFUND_SUMMARY_STATUS = "charge_refunded_summary"
_INACTIVE_DISPUTE_STATUSES = frozenset(
    {
        "won",
        "warning_closed",
        "warning_needs_response",
        "warning_under_review",
    }
)


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
class StripeRefundState:
    id: str
    payment_intent_id: str
    amount_cents: int
    currency: str
    status: str
    created: int


@dataclass(frozen=True, slots=True)
class StripePaymentIntentState:
    id: str
    status: str
    capture_method: str
    amount_cents: int
    amount_received_cents: int
    currency: str
    metadata: dict[str, str]


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
class _StripeEventScope:
    is_local: bool
    purchase_id: str | None = None
    integration_identifier: str | None = None
    payment_intent_id: str | None = None


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
        consumer_disclosure_id: str,
        consumer_disclosure_sha256: str,
        consumer_contract_sha256: str,
        consumer_locale: str,
        idempotency_key: str,
    ) -> StripeCheckoutSession: ...

    def expire_checkout_session(self, session_id: str) -> None: ...

    def retrieve_payment_intent_metadata(
        self,
        payment_intent_id: str,
    ) -> dict[str, str]: ...

    def retrieve_payment_intent_state(
        self,
        payment_intent_id: str,
    ) -> StripePaymentIntentState: ...

    def capture_authorized_payment(
        self,
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState: ...

    def cancel_authorized_payment(
        self,
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState: ...

    def list_payment_intent_refunds(
        self,
        payment_intent_id: str,
    ) -> tuple[StripeRefundState, ...]: ...

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]: ...


class StripeSdkGateway:
    """Narrow Stripe SDK adapter with SDK-level retries disabled."""

    def __init__(self) -> None:
        try:
            settings.assert_stripe_gateway_configuration()
        except RuntimeError as exc:
            raise BillingDisabledError(
                "Stripe webhook reconciliation is not configured",
            ) from exc
        try:
            import stripe
        except ImportError as exc:  # pragma: no cover - guarded by requirements
            raise BillingProviderError("Stripe SDK is unavailable") from exc

        if settings.stripe_restricted_key is None or settings.stripe_webhook_secret is None:
            raise BillingDisabledError(
                "Stripe webhook reconciliation is not configured",
            )
        self._stripe = stripe
        self._webhook_secret = settings.stripe_webhook_secret.get_secret_value().strip()
        self._client = stripe.StripeClient(
            settings.stripe_restricted_key.get_secret_value().strip(),
            stripe_version=STRIPE_API_VERSION,
            base_addresses={"api": settings.stripe_api_base},
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
        consumer_disclosure_id: str,
        consumer_disclosure_sha256: str,
        consumer_contract_sha256: str,
        consumer_locale: str,
        idempotency_key: str,
    ) -> StripeCheckoutSession:
        metadata = {
            "purchase_id": purchase_id,
            "user_id": user_id,
            "package_key": package_key,
            "credits": str(credits),
            "integration_identifier": integration_identifier,
            "catalog_version": CATALOG_VERSION,
            "consumer_disclosure_id": consumer_disclosure_id,
            "consumer_disclosure_sha256": consumer_disclosure_sha256,
            "consumer_contract_sha256": consumer_contract_sha256,
            "consumer_locale": consumer_locale,
            "billing_country": GREEK_B2C_BILLING_COUNTRY,
            "capture_policy": MANUAL_CAPTURE_POLICY,
        }
        session = self._client.v1.checkout.sessions.create(
            {
                "mode": "payment", "submit_type": "pay",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": settings.stripe_success_url,
                "cancel_url": settings.stripe_cancel_url,
                "client_reference_id": user_id,
                "customer_email": customer_email,
                "customer_creation": "always",
                "billing_address_collection": "required",
                "name_collection": {"individual": {"enabled": True}},
                "integration_identifier": integration_identifier,
                "metadata": metadata,
                "payment_intent_data": {
                    "capture_method": "manual",
                    "metadata": metadata,
                    "receipt_email": customer_email,
                    "statement_descriptor_suffix": "GSUBS",
                },
                "expires_at": int(time.time()) + 60 * 60,
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

    def retrieve_payment_intent_metadata(
        self,
        payment_intent_id: str,
    ) -> dict[str, str]:
        return self.retrieve_payment_intent_state(
            payment_intent_id,
        ).metadata

    def retrieve_payment_intent_state(
        self,
        payment_intent_id: str,
    ) -> StripePaymentIntentState:
        try:
            payment_intent = self._client.v1.payment_intents.retrieve(
                payment_intent_id,
            )
        except Exception as exc:
            raise BillingProviderError(
                "Stripe PaymentIntent lookup is temporarily unavailable",
            ) from exc
        return self._normalize_payment_intent_state(
            payment_intent,
            expected_payment_intent_id=payment_intent_id,
        )

    def capture_authorized_payment(
        self,
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState:
        current = self.retrieve_payment_intent_state(payment_intent_id)
        if current.status == "succeeded":
            return current
        if current.status != "requires_capture":
            raise BillingProviderError(
                "Stripe payment authorization is not capturable",
            )
        try:
            captured = self._client.v1.payment_intents.capture(
                payment_intent_id,
                {},
                {"idempotency_key": idempotency_key},
            )
        except Exception as exc:
            raise BillingProviderError(
                "Stripe payment capture is temporarily unavailable",
            ) from exc
        return self._normalize_payment_intent_state(
            captured,
            expected_payment_intent_id=payment_intent_id,
        )

    def cancel_authorized_payment(
        self,
        payment_intent_id: str,
        *,
        idempotency_key: str,
    ) -> StripePaymentIntentState:
        current = self.retrieve_payment_intent_state(payment_intent_id)
        if current.status == "canceled":
            return current
        if current.status != "requires_capture":
            raise BillingProviderError(
                "Stripe payment authorization is not cancelable",
            )
        try:
            canceled = self._client.v1.payment_intents.cancel(
                payment_intent_id,
                {"cancellation_reason": "abandoned"},
                {"idempotency_key": idempotency_key},
            )
        except Exception as exc:
            raise BillingProviderError(
                "Stripe payment authorization cancellation is temporarily unavailable",
            ) from exc
        return self._normalize_payment_intent_state(
            canceled,
            expected_payment_intent_id=payment_intent_id,
        )

    @staticmethod
    def _normalize_payment_intent_state(
        raw_payment_intent: Any,
        *,
        expected_payment_intent_id: str,
    ) -> StripePaymentIntentState:
        if hasattr(raw_payment_intent, "to_dict"):
            raw_payment_intent = raw_payment_intent.to_dict()
        if not isinstance(raw_payment_intent, dict):
            raw_payment_intent = {
                key: getattr(raw_payment_intent, key, None)
                for key in (
                    "id",
                    "status",
                    "capture_method",
                    "amount",
                    "amount_received",
                    "currency",
                    "metadata",
                )
            }
        payment_intent_id = BillingService._stripe_id(
            raw_payment_intent.get("id"),
        )
        status = str(raw_payment_intent.get("status") or "").strip()
        capture_method = str(
            raw_payment_intent.get("capture_method") or "",
        ).strip()
        currency = str(raw_payment_intent.get("currency") or "").lower().strip()
        raw_amount = raw_payment_intent.get("amount")
        raw_amount_received = raw_payment_intent.get("amount_received")
        if isinstance(raw_amount, bool) or isinstance(raw_amount_received, bool):
            raise BillingProviderError(
                "Stripe PaymentIntent state is invalid",
            )
        try:
            amount_cents = int(raw_amount)
            amount_received_cents = int(raw_amount_received)
        except (TypeError, ValueError) as exc:
            raise BillingProviderError(
                "Stripe PaymentIntent state is invalid",
            ) from exc
        metadata = raw_payment_intent.get("metadata")
        if hasattr(metadata, "to_dict"):
            metadata = metadata.to_dict()
        if metadata is None:
            metadata = {}
        if (
            payment_intent_id != expected_payment_intent_id
            or not payment_intent_id.startswith("pi_")
            or len(payment_intent_id) > 255
            or not status
            or len(status) > 64
            or capture_method not in {"automatic", "manual"}
            or amount_cents <= 0
            or amount_received_cents < 0
            or amount_received_cents > amount_cents
            or not currency
            or len(currency) > 8
            or not isinstance(metadata, dict)
        ):
            raise BillingProviderError(
                "Stripe PaymentIntent state is invalid",
            )
        normalized_metadata = {
            str(key): str(value) for key, value in metadata.items() if isinstance(key, str) and isinstance(value, str)
        }
        if len(normalized_metadata) != len(metadata):
            raise BillingProviderError(
                "Stripe PaymentIntent metadata is invalid",
            )
        return StripePaymentIntentState(
            id=payment_intent_id,
            status=status,
            capture_method=capture_method,
            amount_cents=amount_cents,
            amount_received_cents=amount_received_cents,
            currency=currency,
            metadata=normalized_metadata,
        )

    def list_payment_intent_refunds(
        self,
        payment_intent_id: str,
    ) -> tuple[StripeRefundState, ...]:
        """Materialize every Refund page before any local financial mutation."""
        try:
            page = self._client.v1.refunds.list(
                {
                    "payment_intent": payment_intent_id,
                    "limit": 100,
                }
            )
            raw_refunds = list(page.auto_paging_iter())
            refunds = tuple(
                self._normalize_refund_state(
                    raw_refund,
                    payment_intent_id=payment_intent_id,
                )
                for raw_refund in raw_refunds
            )
        except BillingProviderError:
            raise
        except Exception as exc:
            raise BillingProviderError(
                "Stripe refund reconciliation is temporarily unavailable",
            ) from exc

        refund_ids = [refund.id for refund in refunds]
        if len(refund_ids) != len(set(refund_ids)):
            raise BillingProviderError(
                "Stripe refund reconciliation returned duplicate objects",
            )
        return refunds

    @staticmethod
    def _normalize_refund_state(
        raw_refund: Any,
        *,
        payment_intent_id: str,
    ) -> StripeRefundState:
        if hasattr(raw_refund, "to_dict"):
            raw_refund = raw_refund.to_dict()
        if not isinstance(raw_refund, dict):
            raw_refund = {
                key: getattr(raw_refund, key, None)
                for key in (
                    "id",
                    "payment_intent",
                    "amount",
                    "currency",
                    "status",
                    "created",
                )
            }

        refund_id = BillingService._stripe_id(raw_refund.get("id"))
        returned_payment_intent_id = BillingService._stripe_id(
            raw_refund.get("payment_intent"),
        )
        currency = str(raw_refund.get("currency") or "").lower().strip()
        status = str(raw_refund.get("status") or "").lower().strip()
        raw_amount = raw_refund.get("amount")
        raw_created = raw_refund.get("created")
        if isinstance(raw_amount, bool) or isinstance(raw_created, bool):
            raise BillingProviderError(
                "Stripe refund reconciliation returned invalid data",
            )
        try:
            amount_cents = int(raw_amount)
            created = int(raw_created)
        except (TypeError, ValueError) as exc:
            raise BillingProviderError(
                "Stripe refund reconciliation returned invalid data",
            ) from exc
        if (
            not refund_id.startswith("re_")
            or len(refund_id) > 255
            or returned_payment_intent_id != payment_intent_id
            or amount_cents <= 0
            or not currency
            or len(currency) > 8
            or status not in (_ACTIVE_REFUND_STATUSES | _INACTIVE_REFUND_STATUSES)
            or created <= 0
        ):
            raise BillingProviderError(
                "Stripe refund reconciliation returned invalid data",
            )
        return StripeRefundState(
            id=refund_id,
            payment_intent_id=returned_payment_intent_id,
            amount_cents=amount_cents,
            currency=currency,
            status=status,
            created=created,
        )

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            # Keep this boundary typed across Stripe SDK releases: older
            # versions expose an untyped facade while newer releases annotate it.
            construct_event: Callable[..., object] = self._stripe.Webhook.construct_event
            event = construct_event(
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


def public_credit_catalog(locale: str = "el") -> dict[str, Any]:
    packages = credit_packages()
    consumer_contract_approved = consumer_contract_registry_is_approved()
    return {
        "catalog_version": CATALOG_VERSION,
        "currency": "eur",
        "billing_country_scope": [GREEK_B2C_BILLING_COUNTRY],
        "checkout_enabled": (settings.paid_credit_checkout_enabled and consumer_contract_approved),
        "consumer_contract_status": ("approved" if consumer_contract_approved else "unavailable_unapproved"),
        "consumer_contract": (public_consumer_contract(locale) if consumer_contract_approved else None),
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
        consumer_contract: ConsumerContractAcceptance,
        billing_country: str = GREEK_B2C_BILLING_COUNTRY,
    ) -> CheckoutResult:
        normalized_billing_country = billing_country.strip().upper()
        if normalized_billing_country != GREEK_B2C_BILLING_COUNTRY:
            raise BillingValidationError(
                "Paid credit purchases are available only to customers with a Greek billing address",
            )
        with self.db.session() as lock_session:
            self._lock_account_billing(lock_session, user_id)
            if lock_session.get(DbUser, user_id) is None:
                raise BillingConflictError("Account is no longer available")
            return self._create_checkout_locked(
                user_id=user_id,
                customer_email=customer_email,
                package_key=package_key,
                idempotency_key=idempotency_key,
                consumer_contract=consumer_contract,
                billing_country=normalized_billing_country,
            )

    def _create_checkout_locked(
        self,
        *,
        user_id: str,
        customer_email: str,
        package_key: str,
        idempotency_key: str,
        consumer_contract: ConsumerContractAcceptance,
        billing_country: str,
    ) -> CheckoutResult:
        gateway = self._configured_gateway()
        incoming_key = self._validate_idempotency_key(idempotency_key)
        package = self._package(package_key)
        purchase = self._ensure_purchase(
            user_id=user_id,
            package=package,
            idempotency_key=incoming_key,
            consumer_contract=consumer_contract,
            billing_country=billing_country,
        )
        if purchase.status == "checkout_created" and purchase.checkout_url:
            return self._checkout_result(purchase)
        if purchase.fulfilled_at is not None:
            return self._checkout_result(purchase)
        if purchase.status not in {"creating", "checkout_created"}:
            raise BillingConflictError("This checkout request cannot be reused")

        try:
            consumer_snapshot = purchase.snapshot.get("consumer_contract")
            if not isinstance(consumer_snapshot, dict):
                raise BillingValidationError(
                    "Consumer-contract snapshot is unavailable",
                )
            checkout = gateway.create_checkout_session(
                price_id=str(purchase.snapshot["stripe_price_id"]),
                user_id=user_id,
                customer_email=customer_email,
                purchase_id=purchase.id,
                package_key=purchase.package_key,
                credits=purchase.credits,
                integration_identifier=purchase.integration_identifier,
                consumer_disclosure_id=str(
                    consumer_snapshot.get("disclosure_id") or "",
                ),
                consumer_disclosure_sha256=str(
                    consumer_snapshot.get("disclosure_sha256") or "",
                ),
                consumer_contract_sha256=str(
                    purchase.snapshot.get("consumer_contract_sha256") or "",
                ),
                consumer_locale=str(consumer_snapshot.get("locale") or ""),
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
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase.id).with_for_update().limit(1)
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

    def prepare_account_deletion(
        self,
        *,
        session: Session,
        user_id: str,
    ) -> None:
        """Lock billing state and remove only expired terminal unpaid attempts."""
        self._lock_account_billing(session, user_id)
        purchases = list(
            session.scalars(select(DbCreditPurchase).where(DbCreditPurchase.user_id == user_id).with_for_update())
        )
        open_purchase = next(
            (
                purchase
                for purchase in purchases
                if purchase.fulfilled_at is None
                and purchase.payment_snapshot is None
                and purchase.status
                not in {
                    "expired",
                    "failed",
                }
            ),
            None,
        )
        if open_purchase is not None:
            raise BillingConflictError(
                "Account deletion is blocked while a payment is still open",
            )
        purchase_ids = [purchase.id for purchase in purchases]
        if purchase_ids:
            pending_withdrawal = session.scalar(
                select(DbBillingWithdrawalRequest)
                .where(
                    DbBillingWithdrawalRequest.purchase_id.in_(
                        purchase_ids,
                    ),
                    DbBillingWithdrawalRequest.status == "pending_manual_review",
                    ~select(DbBillingWithdrawalResolution.id)
                    .where(
                        DbBillingWithdrawalResolution.withdrawal_id == DbBillingWithdrawalRequest.id,
                    )
                    .exists(),
                )
                .with_for_update()
                .limit(1)
            )
            if pending_withdrawal is not None:
                raise BillingConflictError(
                    "Account deletion is blocked while a withdrawal request "
                    "is pending manual review, so its account-vault "
                    "acknowledgement cannot be orphaned. Deletion can resume "
                    "only after reviewed resolution and durable delivery."
                )

        durable_child_purchase_ids: set[str] = set()
        if purchase_ids:
            durable_child_purchase_ids.update(
                session.scalars(
                    select(DbBillingInvoice.purchase_id).where(
                        DbBillingInvoice.purchase_id.in_(purchase_ids),
                    )
                )
            )
            durable_child_purchase_ids.update(
                session.scalars(
                    select(DbCreditPurchaseReversal.purchase_id).where(
                        DbCreditPurchaseReversal.purchase_id.in_(purchase_ids),
                    )
                )
            )
            durable_child_purchase_ids.update(
                session.scalars(
                    select(DbBillingContractConfirmation.purchase_id).where(
                        DbBillingContractConfirmation.purchase_id.in_(
                            purchase_ids,
                        ),
                    )
                )
            )
            durable_child_purchase_ids.update(
                session.scalars(
                    select(DbBillingWithdrawalRequest.purchase_id).where(
                        DbBillingWithdrawalRequest.purchase_id.in_(
                            purchase_ids,
                        ),
                    )
                )
            )
            durable_child_purchase_ids.update(
                session.scalars(
                    select(DbBillingAdjustmentRecord.purchase_id).where(
                        DbBillingAdjustmentRecord.purchase_id.in_(
                            purchase_ids,
                        ),
                    )
                )
            )
            durable_child_purchase_ids.update(
                session.scalars(
                    select(DbBillingWithdrawalResolution.purchase_id).where(
                        DbBillingWithdrawalResolution.purchase_id.in_(
                            purchase_ids,
                        ),
                    )
                )
            )

        retention_cutoff = max(1, int(time.time()) - 5)
        expired_unpaid_exists = any(
            purchase.fulfilled_at is None
            and purchase.payment_snapshot is None
            and purchase.payment_intent_id is None
            and purchase.status in {"expired", "failed"}
            and purchase.financial_retention_until <= retention_cutoff
            and purchase.id not in durable_child_purchase_ids
            for purchase in purchases
        )
        if expired_unpaid_exists:
            # The database independently validates this transaction-local
            # cutoff against its own clock and every durable child record.
            session.execute(
                text("SELECT set_config('gsubs.billing_retention_cutoff', :cutoff, true)"),
                {"cutoff": str(retention_cutoff)},
            )

        for purchase in purchases:
            is_financial_record = (
                purchase.fulfilled_at is not None
                or purchase.payment_snapshot is not None
                or purchase.payment_intent_id is not None
            )
            purchase.checkout_url = None
            if (
                not is_financial_record
                and purchase.status in {"expired", "failed"}
                and purchase.financial_retention_until <= retention_cutoff
                and purchase.id not in durable_child_purchase_ids
            ):
                session.delete(purchase)

    @staticmethod
    def _lock_account_billing(session: Session, user_id: str) -> None:
        lock_key = BillingService._advisory_lock_key(
            f"billing-account:{user_id}",
        )
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    def verify_and_process_webhook(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> WebhookResult:
        gateway = self._webhook_gateway()
        event = gateway.verify_webhook(payload, signature)
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if not event_id or len(event_id) > 255 or not event_type or len(event_type) > 128:
            raise BillingValidationError("Invalid Stripe event envelope")
        event_object = event.get("data", {}).get("object")
        if not isinstance(event_object, dict):
            raise BillingValidationError("Invalid Stripe event object")
        validated_livemode = self._validated_event_livemode(
            event_type,
            event.get("livemode"),
        )
        if event_type in _CHECKOUT_EVENT_TYPES:
            self._validate_checkout_session_id_mode(
                self._stripe_id(event_object.get("id")),
            )

        payload_hash = hashlib.sha256(payload).hexdigest()
        lock_key = int.from_bytes(
            hashlib.sha256(event_id.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        # Serialize identical deliveries for the complete processing window.
        # The PaymentIntent lock also orders a reversal that arrives while the
        # first paid fulfillment is still uncommitted and therefore not yet
        # discoverable through the purchase row.
        with self.db.session() as lock_session:
            lock_session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            payment_intent_id = self._stripe_id(
                event_object.get("payment_intent"),
            )
            if payment_intent_id.startswith("pi_"):
                payment_intent_lock_key = self._advisory_lock_key(
                    f"stripe-payment-intent:{payment_intent_id}",
                )
                lock_session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": payment_intent_lock_key},
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
                event_scope = self._resolve_event_scope(
                    lock_session,
                    event_type=event_type,
                    obj=event_object,
                )
                if event_scope.payment_intent_id and event_scope.payment_intent_id != payment_intent_id:
                    payment_intent_lock_key = self._advisory_lock_key(
                        f"stripe-payment-intent:{event_scope.payment_intent_id}",
                    )
                    lock_session.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_key)"),
                        {"lock_key": payment_intent_lock_key},
                    )
                if event_scope.purchase_id:
                    purchase_lock_key = self._advisory_lock_key(
                        f"credit-purchase:{event_scope.purchase_id}",
                    )
                    lock_session.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_key)"),
                        {"lock_key": purchase_lock_key},
                    )
                status = self._process_event(
                    event_id,
                    event_type,
                    event_object,
                    event_scope=event_scope,
                    provider_event_created=event.get("created"),
                    livemode=validated_livemode,
                )
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
        self._validate_checkout_session_id_mode(checkout_session_id)
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
        if not settings.paid_credit_checkout_enabled or not consumer_contract_registry_is_approved():
            raise BillingDisabledError("Credit purchases are not enabled yet")
        if self._gateway is None:
            self._gateway = StripeSdkGateway()
        return self._gateway

    def _webhook_gateway(self) -> BillingGateway:
        """Keep signed reconciliation active even when new sales are paused."""
        if self._gateway is None:
            self._gateway = StripeSdkGateway()
        return self._gateway

    def _consumer_acceptance_timestamp(self) -> int:
        """Server clock used for the consumer's Checkout acceptance."""
        return int(time.time())

    def _ensure_purchase(
        self,
        *,
        user_id: str,
        package: CreditPackage,
        idempotency_key: str,
        consumer_contract: ConsumerContractAcceptance,
        billing_country: str,
    ) -> DbCreditPurchase:
        now = self._consumer_acceptance_timestamp()
        purchase_id = uuid.uuid4().hex
        integration_identifier = self._integration_identifier()
        try:
            consumer_snapshot = build_consumer_contract_snapshot(
                consumer_contract,
                expected_catalog_version=CATALOG_VERSION,
                accepted_at=now,
            )
        except ConsumerContractValidationError as exc:
            raise BillingValidationError(str(exc)) from exc
        snapshot = {
            "catalog_version": CATALOG_VERSION,
            "package_key": package.key,
            "credits": package.credits,
            "amount_eur_cents": package.amount_eur_cents,
            "currency": "eur",
            "stripe_price_id": package.price_id,
            "billing_country": billing_country,
            "capture_policy": MANUAL_CAPTURE_POLICY,
            "consumer_contract": consumer_snapshot,
            "consumer_contract_sha256": consumer_contract_snapshot_sha256(
                consumer_snapshot,
            ),
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
                    reversed_amount_cents=0,
                    snapshot=snapshot,
                    financial_retention_until=(now + UNPAID_PURCHASE_RETENTION_SECONDS),
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[DbCreditPurchase.idempotency_key])
            )
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.idempotency_key == idempotency_key).limit(1)
            )
            if purchase is None:
                raise BillingProviderError("Could not create checkout purchase")
            recorded_consumer_contract = (
                purchase.snapshot.get("consumer_contract") if isinstance(purchase.snapshot, dict) else None
            )
            recorded_accepted_at = (
                recorded_consumer_contract.get("accepted_at") if isinstance(recorded_consumer_contract, dict) else None
            )
            if (
                isinstance(recorded_accepted_at, bool)
                or not isinstance(recorded_accepted_at, int)
                or recorded_accepted_at <= 0
            ):
                raise BillingConflictError(
                    "Stored consumer-contract evidence is invalid",
                )
            try:
                expected_consumer_snapshot = build_consumer_contract_snapshot(
                    consumer_contract,
                    expected_catalog_version=CATALOG_VERSION,
                    accepted_at=recorded_accepted_at,
                )
            except ConsumerContractValidationError as exc:
                raise BillingValidationError(str(exc)) from exc
            expected_snapshot = {
                "catalog_version": CATALOG_VERSION,
                "package_key": package.key,
                "credits": package.credits,
                "amount_eur_cents": package.amount_eur_cents,
                "currency": "eur",
                "stripe_price_id": package.price_id,
                "billing_country": billing_country,
                "capture_policy": MANUAL_CAPTURE_POLICY,
                "consumer_contract": expected_consumer_snapshot,
                "consumer_contract_sha256": (
                    consumer_contract_snapshot_sha256(
                        expected_consumer_snapshot,
                    )
                ),
            }
            if (
                purchase.user_id != user_id
                or purchase.package_key != package.key
                or purchase.credits != package.credits
                or purchase.amount_eur_cents != package.amount_eur_cents
                or purchase.currency.lower() != "eur"
                or purchase.snapshot != expected_snapshot
            ):
                raise BillingConflictError("Idempotency key was used for another purchase")
            return purchase

    def _process_event(
        self,
        event_id: str,
        event_type: str,
        obj: dict[str, Any],
        *,
        event_scope: _StripeEventScope,
        provider_event_created: Any,
        livemode: Any,
    ) -> str:
        if event_type in _RECOGNIZED_EVENT_TYPES and not event_scope.is_local:
            return "ignored"
        if event_type == "checkout.session.completed":
            if self._manual_capture_required(
                purchase_id=event_scope.purchase_id,
                obj=obj,
            ):
                self._capture_and_fulfill_checkout(
                    obj,
                    purchase_id=event_scope.purchase_id,
                    provider_event_created=self._provider_event_created(
                        provider_event_created,
                    ),
                    livemode=self._event_livemode(livemode),
                )
            elif str(obj.get("payment_status") or "") == "unpaid":
                self._await_checkout_payment(
                    obj,
                    purchase_id=event_scope.purchase_id,
                )
            else:
                self._fulfill_checkout(
                    obj,
                    purchase_id=event_scope.purchase_id,
                    provider_event_created=self._provider_event_created(
                        provider_event_created,
                    ),
                    livemode=self._event_livemode(livemode),
                )
            return "processed"
        if event_type == "checkout.session.async_payment_succeeded":
            if self._manual_capture_required(
                purchase_id=event_scope.purchase_id,
                obj=obj,
            ):
                raise BillingValidationError(
                    "Manual-capture Checkout cannot use asynchronous fulfillment",
                )
            self._fulfill_checkout(
                obj,
                purchase_id=event_scope.purchase_id,
                provider_event_created=self._provider_event_created(
                    provider_event_created,
                ),
                livemode=self._event_livemode(livemode),
            )
            return "processed"
        if event_type == "checkout.session.expired":
            self._expire_checkout(obj)
            return "processed"
        if event_type == "checkout.session.async_payment_failed":
            self._fail_async_checkout(obj)
            return "processed"
        if event_type in _REVERSAL_EVENT_TYPES:
            validated_provider_event_created = self._provider_event_created(
                provider_event_created,
            )
            authoritative_refunds = None
            if event_type == "charge.refunded":
                payment_intent_id = event_scope.payment_intent_id
                if not payment_intent_id:
                    raise BillingProviderError(
                        "Local reversal PaymentIntent is not available yet",
                    )
                authoritative_refunds = self._webhook_gateway().list_payment_intent_refunds(
                    payment_intent_id,
                )
            self._apply_reversal_event(
                obj,
                event_id=event_id,
                event_type=event_type,
                purchase_id=event_scope.purchase_id,
                integration_identifier=event_scope.integration_identifier,
                resolved_payment_intent_id=event_scope.payment_intent_id,
                authoritative_refunds=authoritative_refunds,
                provider_event_created=validated_provider_event_created,
            )
            return "processed"
        return "ignored"

    def _manual_capture_required(
        self,
        *,
        purchase_id: str | None,
        obj: dict[str, Any],
    ) -> bool:
        if purchase_id:
            with self.db.session() as session:
                purchase = session.get(DbCreditPurchase, purchase_id)
                if purchase is not None and isinstance(
                    purchase.snapshot,
                    dict,
                ):
                    return purchase.snapshot.get("capture_policy") == MANUAL_CAPTURE_POLICY
        metadata = obj.get("metadata")
        return isinstance(metadata, dict) and metadata.get("capture_policy") == MANUAL_CAPTURE_POLICY

    def _capture_and_fulfill_checkout(
        self,
        obj: dict[str, Any],
        *,
        purchase_id: str | None,
        provider_event_created: int,
        livemode: bool,
    ) -> None:
        session_id = str(obj.get("id") or "")
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            raise BillingValidationError("Checkout metadata is missing")
        if not purchase_id:
            raise BillingProviderError(
                "Local Checkout purchase is not available yet",
            )

        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise BillingProviderError(
                    "Local Checkout purchase is not available yet",
                )
            self._validate_manual_capture_checkout(
                obj,
                metadata,
                purchase,
                session_id,
            )
            if purchase.fulfilled_at is not None:
                return
            payment_intent_id = self._stripe_id(
                obj.get("payment_intent"),
            )

        gateway = self._webhook_gateway()
        authorized = gateway.retrieve_payment_intent_state(
            payment_intent_id,
        )
        self._validate_manual_payment_intent(
            authorized,
            purchase=purchase,
            expected_payment_intent_id=payment_intent_id,
            expected_user_id=str(metadata.get("user_id") or ""),
            allowed_statuses=frozenset(
                {"requires_capture", "succeeded", "canceled"},
            ),
        )

        try:
            validate_checkout_accounting_eligibility(
                purchase=purchase,
                checkout=obj,
                stripe_event_created=provider_event_created,
                livemode=livemode,
            )
        except CheckoutAccountingIneligibleError:
            canceled = gateway.cancel_authorized_payment(
                payment_intent_id,
                idempotency_key=f"gsubs-cancel-{purchase.id}",
            )
            self._validate_manual_payment_intent(
                canceled,
                purchase=purchase,
                expected_payment_intent_id=payment_intent_id,
                expected_user_id=str(metadata.get("user_id") or ""),
                allowed_statuses=frozenset({"canceled"}),
            )
            if canceled.amount_received_cents != 0:
                raise BillingProviderError(
                    "Canceled Stripe authorization reports received funds",
                )
            self._mark_ineligible_authorization_canceled(
                purchase.id,
            )
            return
        except ValueError as exc:
            raise BillingValidationError(str(exc)) from exc

        if authorized.status == "canceled":
            raise BillingProviderError(
                "Stripe payment authorization was canceled before capture",
            )
        captured = gateway.capture_authorized_payment(
            payment_intent_id,
            idempotency_key=f"gsubs-capture-{purchase.id}",
        )
        self._validate_manual_payment_intent(
            captured,
            purchase=purchase,
            expected_payment_intent_id=payment_intent_id,
            expected_user_id=str(metadata.get("user_id") or ""),
            allowed_statuses=frozenset({"succeeded"}),
        )
        if captured.amount_received_cents != purchase.amount_eur_cents:
            raise BillingProviderError(
                "Captured Stripe payment amount is invalid",
            )
        self._fulfill_checkout(
            obj,
            purchase_id=purchase.id,
            provider_event_created=provider_event_created,
            livemode=livemode,
            capture_evidence=PaymentCaptureEvidence(
                payment_intent_id=captured.id,
                status=captured.status,
                amount_cents=captured.amount_cents,
                amount_received_cents=captured.amount_received_cents,
                currency=captured.currency,
                capture_method="manual",
                capture_policy=MANUAL_CAPTURE_POLICY,
            ),
        )

    def _fulfill_checkout(
        self,
        obj: dict[str, Any],
        *,
        purchase_id: str | None,
        provider_event_created: int,
        livemode: bool,
        capture_evidence: PaymentCaptureEvidence | None = None,
    ) -> None:
        session_id = str(obj.get("id") or "")
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            raise BillingValidationError("Checkout metadata is missing")
        if not purchase_id:
            raise BillingProviderError("Local Checkout purchase is not available yet")
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise BillingProviderError(
                    "Local Checkout purchase is not available yet",
                )
            self._validate_fulfillment_object(
                obj,
                metadata,
                purchase,
                session_id,
                manual_capture=capture_evidence is not None,
            )
            if purchase.fulfilled_at is not None:
                return
            try:
                financial_record = build_paid_financial_record(
                    purchase=purchase,
                    checkout=obj,
                    stripe_event_created=provider_event_created,
                    livemode=livemode,
                    capture_evidence=capture_evidence,
                )
            except ValueError as exc:
                raise BillingValidationError(str(exc)) from exc

            existing_snapshots = (
                purchase.payment_snapshot,
                purchase.customer_snapshot,
                purchase.tax_snapshot,
            )
            if all(snapshot is None for snapshot in existing_snapshots):
                purchase.payment_snapshot = financial_record.payment_snapshot
                purchase.customer_snapshot = financial_record.customer_snapshot
                purchase.tax_snapshot = financial_record.tax_snapshot
            elif any(snapshot is None for snapshot in existing_snapshots):
                raise BillingConflictError(
                    "Paid checkout financial snapshots are incomplete",
                )
            elif existing_snapshots != (
                financial_record.payment_snapshot,
                financial_record.customer_snapshot,
                financial_record.tax_snapshot,
            ):
                raise BillingConflictError(
                    "Paid checkout financial snapshots conflict with signed Checkout evidence",
                )

            expected_invoice = new_pending_invoice(
                purchase_id=purchase.id,
                record=financial_record,
                created_at=provider_event_created,
            )
            invoices = tuple(
                session.scalars(
                    select(DbBillingInvoice)
                    .where((DbBillingInvoice.purchase_id == purchase.id) | (DbBillingInvoice.id == expected_invoice.id))
                    .with_for_update()
                    .limit(2)
                )
            )
            if len(invoices) > 1:
                raise BillingConflictError(
                    "Paid checkout invoice identity is ambiguous",
                )
            invoice = invoices[0] if invoices else None
            if invoice is None:
                session.add(expected_invoice)
            elif (
                invoice.id != expected_invoice.id
                or invoice.purchase_id != expected_invoice.purchase_id
                or invoice.provider != expected_invoice.provider
                or invoice.document_kind != expected_invoice.document_kind
                or invoice.document_status != expected_invoice.document_status
                or invoice.aade_document_type != expected_invoice.aade_document_type
                or invoice.aade_series != expected_invoice.aade_series
                or invoice.aade_aa != expected_invoice.aade_aa
                or invoice.aade_mark != expected_invoice.aade_mark
                or invoice.issued_at != expected_invoice.issued_at
                or invoice.recorded_by_user_id != expected_invoice.recorded_by_user_id
                or invoice.recorded_at != expected_invoice.recorded_at
                or invoice.document_snapshot != expected_invoice.document_snapshot
                or invoice.financial_retention_until != expected_invoice.financial_retention_until
                or invoice.created_at != expected_invoice.created_at
                or invoice.updated_at != expected_invoice.updated_at
            ):
                raise BillingConflictError(
                    "Paid checkout invoice conflicts with signed Checkout evidence",
                )

            purchase.financial_retention_until = max(
                int(purchase.financial_retention_until),
                financial_record.retention_until,
            )
            payment_intent_id = self._stripe_id(obj.get("payment_intent"))
            if purchase.payment_intent_id not in {None, payment_intent_id}:
                raise BillingValidationError(
                    "Checkout PaymentIntent conflicts with its purchase",
                )
            purchase.payment_intent_id = payment_intent_id

            confirmation_generated_at = int(time.time())
            confirmation = session.scalar(
                select(DbBillingContractConfirmation)
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase.id,
                )
                .limit(1)
            )
            if confirmation is None:
                try:
                    confirmation = new_contract_confirmation(
                        purchase=purchase,
                        contract_concluded_at=provider_event_created,
                        generated_at=confirmation_generated_at,
                    )
                except BillingConsumerRecordValidationError as exc:
                    raise BillingValidationError(str(exc)) from exc
                session.add(confirmation)
                # REGRESSION: durable contract evidence must be persisted in the
                # same transaction before any paid credits can be granted.
                session.flush()
            try:
                verify_contract_confirmation(
                    confirmation,
                    purchase=purchase,
                )
            except BillingConsumerRecordConflictError as exc:
                raise BillingConflictError(str(exc)) from exc

            now = int(time.time())
            purchase.updated_at = now
            purchase_user_id = purchase.user_id
            if purchase_user_id is None:
                purchase.fulfilled_at = now
                purchase.status = "manual_review_account_deleted"
                purchase.error = "Paid Checkout completed after account deletion"
                purchase.checkout_url = None
                return

            credits_to_grant = max(
                0,
                purchase.credits - purchase.reversed_credits,
            )
            if credits_to_grant > 0:
                self.points_store.apply_paid_purchase_once_in_session(
                    session,
                    purchase_user_id,
                    credits_to_grant,
                    purchase_id=purchase.id,
                    transaction_id=make_idempotency_id(
                        "stripe",
                        "purchase",
                        purchase.id,
                    ),
                )

            purchase.fulfilled_at = now
            purchase.status = self._reversal_status(purchase)
            purchase.error = None
            purchase.checkout_url = None
            purchase.updated_at = now

    def _await_checkout_payment(
        self,
        obj: dict[str, Any],
        *,
        purchase_id: str | None,
    ) -> None:
        session_id = str(obj.get("id") or "")
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            raise BillingValidationError("Checkout metadata is missing")
        if not purchase_id:
            raise BillingProviderError("Local Checkout purchase is not available yet")
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise BillingProviderError(
                    "Local Checkout purchase is not available yet",
                )
            self._validate_checkout_identity(obj, metadata, purchase, session_id)
            if str(obj.get("payment_status") or "") != "unpaid":
                raise BillingValidationError("Checkout payment state is invalid")
            if purchase.fulfilled_at is not None or purchase.status in {"expired", "failed"}:
                return
            purchase.status = "awaiting_payment"
            purchase.error = None
            purchase.checkout_url = None
            purchase.updated_at = int(time.time())

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
                purchase.checkout_url = None
                purchase.updated_at = int(time.time())

    def _fail_async_checkout(self, obj: dict[str, Any]) -> None:
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
                purchase.status = "failed"
                purchase.error = "Stripe asynchronous payment failed"
                purchase.checkout_url = None
                purchase.updated_at = int(time.time())

    def _resolve_event_scope(
        self,
        session: Session,
        *,
        event_type: str,
        obj: dict[str, Any],
    ) -> _StripeEventScope:
        """Resolve ownership before mutating a shared Stripe account event."""
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            metadata = obj.get("metadata")
            purchase_id = str(metadata.get("purchase_id") or "") if isinstance(metadata, dict) else ""
            integration_identifier = (
                str(metadata.get("integration_identifier") or "") if isinstance(metadata, dict) else ""
            )
            session_id = self._stripe_id(obj.get("id"))
            known_purchase_id = session.scalar(
                select(DbCreditPurchase.id)
                .where((DbCreditPurchase.id == purchase_id) | (DbCreditPurchase.checkout_session_id == session_id))
                .limit(1)
            )
            if known_purchase_id:
                return _StripeEventScope(
                    is_local=True,
                    purchase_id=known_purchase_id,
                    payment_intent_id=self._stripe_id(
                        obj.get("payment_intent"),
                    )
                    or None,
                )
            if self._is_local_integration_identifier(integration_identifier):
                if not _PURCHASE_ID_RE.fullmatch(purchase_id):
                    raise BillingValidationError(
                        "Local Checkout metadata has an invalid purchase id",
                    )
                return _StripeEventScope(
                    is_local=True,
                    purchase_id=purchase_id,
                    integration_identifier=integration_identifier,
                    payment_intent_id=self._stripe_id(
                        obj.get("payment_intent"),
                    )
                    or None,
                )
            return _StripeEventScope(is_local=False)

        if event_type in {
            "checkout.session.expired",
            "checkout.session.async_payment_failed",
        }:
            session_id = str(obj.get("id") or "")
            if not session_id:
                raise BillingValidationError("Checkout Session id is missing")
            known_session_purchase_id = session.scalar(
                select(DbCreditPurchase.id).where(DbCreditPurchase.checkout_session_id == session_id).limit(1)
            )
            return _StripeEventScope(
                is_local=known_session_purchase_id is not None,
                purchase_id=known_session_purchase_id,
            )

        if event_type in _REVERSAL_EVENT_TYPES:
            payment_intent_id = self._stripe_id(obj.get("payment_intent"))
            if not payment_intent_id:
                provider_reversal_id = self._stripe_id(obj.get("id"))
                if not provider_reversal_id or len(provider_reversal_id) > 255:
                    return _StripeEventScope(is_local=False)
                known_reversal = session.execute(
                    select(
                        DbCreditPurchaseReversal.purchase_id,
                        DbCreditPurchase.payment_intent_id,
                    )
                    .join(
                        DbCreditPurchase,
                        DbCreditPurchase.id == DbCreditPurchaseReversal.purchase_id,
                    )
                    .where(
                        DbCreditPurchaseReversal.provider == "stripe",
                        DbCreditPurchaseReversal.provider_reversal_id == provider_reversal_id,
                    )
                    .limit(1)
                ).one_or_none()
                if known_reversal is None:
                    return _StripeEventScope(is_local=False)
                known_purchase_id, known_payment_intent_id = known_reversal
                if not known_payment_intent_id:
                    raise BillingProviderError(
                        "Local reversal PaymentIntent is not available yet",
                    )
                return _StripeEventScope(
                    is_local=True,
                    purchase_id=known_purchase_id,
                    payment_intent_id=known_payment_intent_id,
                )
            known_payment_purchase_id = session.scalar(
                select(DbCreditPurchase.id).where(DbCreditPurchase.payment_intent_id == payment_intent_id).limit(1)
            )
            if known_payment_purchase_id:
                return _StripeEventScope(
                    is_local=True,
                    purchase_id=known_payment_purchase_id,
                    payment_intent_id=payment_intent_id,
                )

            metadata = self._payment_intent_metadata(obj)
            integration_identifier = str(
                metadata.get("integration_identifier") or "",
            )
            if not self._is_local_integration_identifier(
                integration_identifier,
            ):
                return _StripeEventScope(is_local=False)
            purchase_id = str(metadata.get("purchase_id") or "")
            if not _PURCHASE_ID_RE.fullmatch(purchase_id):
                raise BillingValidationError(
                    "Local PaymentIntent metadata has an invalid purchase id",
                )
            return _StripeEventScope(
                is_local=True,
                purchase_id=purchase_id,
                integration_identifier=integration_identifier,
                payment_intent_id=payment_intent_id,
            )
        return _StripeEventScope(is_local=False)

    def _payment_intent_metadata(
        self,
        obj: dict[str, Any],
    ) -> dict[str, str]:
        raw_payment_intent = obj.get("payment_intent")
        if isinstance(raw_payment_intent, dict):
            raw_metadata = raw_payment_intent.get("metadata")
            if isinstance(raw_metadata, dict):
                return {
                    str(key): str(value)
                    for key, value in raw_metadata.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
        payment_intent_id = self._stripe_id(raw_payment_intent)
        try:
            metadata = self._webhook_gateway().retrieve_payment_intent_metadata(
                payment_intent_id,
            )
        except BillingProviderError:
            raise
        except Exception as exc:
            raise BillingProviderError(
                "Stripe PaymentIntent lookup is temporarily unavailable",
            ) from exc
        if not isinstance(metadata, dict):
            raise BillingProviderError(
                "Stripe PaymentIntent metadata is unavailable",
            )
        return metadata

    @staticmethod
    def _is_local_integration_identifier(value: str) -> bool:
        return _LOCAL_INTEGRATION_RE.fullmatch(value) is not None

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
        purchase_id: str | None,
        integration_identifier: str | None,
        resolved_payment_intent_id: str | None,
        authoritative_refunds: tuple[StripeRefundState, ...] | None,
        provider_event_created: int,
    ) -> None:
        payment_intent_id = self._stripe_id(obj.get("payment_intent")) or resolved_payment_intent_id or ""
        if not payment_intent_id:
            raise BillingProviderError(
                "Local reversal PaymentIntent is not available yet",
            )
        if not purchase_id:
            raise BillingProviderError("Local reversal purchase is not available yet")
        provider_reversal_id = self._stripe_id(obj.get("id"))
        if not provider_reversal_id or len(provider_reversal_id) > 255:
            raise BillingValidationError("Reversal object id is invalid")

        currency = str(obj.get("currency") or "").lower().strip()
        if not currency or len(currency) > 8:
            raise BillingValidationError("Reversal currency is invalid")
        is_charge_refund_summary = event_type == "charge.refunded"
        is_refund_object = event_type in _REFUND_OBJECT_EVENT_TYPES
        if is_charge_refund_summary and authoritative_refunds is None:
            raise BillingProviderError(
                "Stripe refund reconciliation is unavailable",
            )
        if not is_charge_refund_summary and authoritative_refunds is not None:
            raise BillingValidationError(
                "Unexpected authoritative refund reconciliation",
            )
        raw_amount = obj.get("amount_refunded") if is_charge_refund_summary else obj.get("amount")
        if raw_amount is None or isinstance(raw_amount, bool):
            raise BillingValidationError("Reversal amount is invalid")
        try:
            amount_cents = int(raw_amount)
        except (TypeError, ValueError) as exc:
            raise BillingValidationError("Reversal amount is invalid") from exc

        kind = "refund" if is_charge_refund_summary or is_refund_object else "dispute"
        if is_charge_refund_summary:
            if not provider_reversal_id.startswith("ch_"):
                raise BillingValidationError("Refund summary object id is invalid")
            status = _CHARGE_REFUND_SUMMARY_STATUS
            active = True
        elif is_refund_object:
            if not provider_reversal_id.startswith("re_"):
                raise BillingValidationError("Refund object id is invalid")
            status = str(obj.get("status") or "").lower().strip()
            if status not in _ACTIVE_REFUND_STATUSES | _INACTIVE_REFUND_STATUSES:
                raise BillingValidationError("Refund status is invalid")
            if event_type == "refund.failed" and status not in _INACTIVE_REFUND_STATUSES:
                raise BillingValidationError("Failed refund status is invalid")
            active = status in _ACTIVE_REFUND_STATUSES
        else:
            status = str(obj.get("status") or "").lower().strip()
            if not status or len(status) > 64:
                raise BillingValidationError("Dispute status is invalid")
            active = self._dispute_active(
                event_type=event_type,
                status=status,
            )

        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise BillingProviderError(
                    "Local reversal purchase is not available yet",
                )
            if integration_identifier is not None and (purchase.integration_identifier != integration_identifier):
                raise BillingValidationError(
                    "PaymentIntent namespace conflicts with its purchase",
                )
            if purchase.payment_intent_id not in {None, payment_intent_id}:
                raise BillingValidationError(
                    "Reversal PaymentIntent conflicts with its purchase",
                )
            if currency != purchase.currency.lower():
                raise BillingValidationError("Reversal currency mismatch")
            if amount_cents <= 0 or amount_cents > purchase.amount_eur_cents:
                raise BillingValidationError("Reversal amount is invalid")
            purchase.payment_intent_id = payment_intent_id

            now = int(time.time())
            reversal = session.scalar(
                select(DbCreditPurchaseReversal)
                .where(
                    DbCreditPurchaseReversal.provider == "stripe",
                    DbCreditPurchaseReversal.provider_reversal_id == provider_reversal_id,
                )
                .with_for_update()
                .limit(1)
            )
            if reversal is None:
                reversal = DbCreditPurchaseReversal(
                    id=uuid.uuid4().hex,
                    purchase_id=purchase.id,
                    provider="stripe",
                    provider_reversal_id=provider_reversal_id,
                    provider_event_id=event_id,
                    provider_event_created=provider_event_created,
                    kind=kind,
                    amount_cents=amount_cents,
                    currency=currency,
                    status=status,
                    active=active,
                    created_at=now,
                    updated_at=now,
                )
                session.add(reversal)
            else:
                update_reversal = True
                if (
                    reversal.purchase_id != purchase.id
                    or reversal.kind != kind
                    or reversal.currency.lower() != currency
                ):
                    raise BillingValidationError(
                        "Reversal object conflicts with its purchase",
                    )
                if is_charge_refund_summary:
                    update_reversal = self._newer_cumulative_refund_state(
                        reversal,
                        event_id=event_id,
                        provider_event_created=provider_event_created,
                        amount_cents=amount_cents,
                    )
                elif is_refund_object:
                    if reversal.amount_cents != amount_cents:
                        raise BillingValidationError(
                            "Refund amount conflicts with its prior state",
                        )
                    if self._stale_refund_state(
                        reversal,
                        event_id=event_id,
                        provider_event_created=provider_event_created,
                        status=status,
                    ):
                        return
                else:
                    if reversal.amount_cents != amount_cents:
                        raise BillingValidationError(
                            "Dispute amount conflicts with its prior state",
                        )
                    if self._stale_dispute_state(
                        reversal,
                        event_id=event_id,
                        provider_event_created=provider_event_created,
                        active=active,
                    ):
                        return

                if update_reversal:
                    reversal.provider_event_id = event_id
                    reversal.provider_event_created = provider_event_created
                    reversal.amount_cents = amount_cents
                    reversal.status = status
                    reversal.active = active
                    reversal.updated_at = now

            if authoritative_refunds is not None:
                self._upsert_authoritative_refunds_in_session(
                    session,
                    purchase=purchase,
                    payment_intent_id=payment_intent_id,
                    refunds=authoritative_refunds,
                    charge_refunded_amount_cents=amount_cents,
                    reconciliation_event_id=event_id,
                    reconciliation_event_created=provider_event_created,
                    now=now,
                )

            session.flush()
            reversals = list(
                session.scalars(
                    select(DbCreditPurchaseReversal).where(
                        DbCreditPurchaseReversal.purchase_id == purchase.id,
                    )
                )
            )
            individual_refunds = [
                item for item in reversals if item.kind == "refund" and self._is_individual_refund(item)
            ]
            individual_refund_cents = sum(item.amount_cents for item in individual_refunds if item.active)
            legacy_refund_cents = max(
                (item.amount_cents for item in reversals if self._is_legacy_refund_baseline(item) and item.active),
                default=0,
            )
            if individual_refunds:
                active_refunded_cents = max(
                    individual_refund_cents,
                    legacy_refund_cents,
                )
            else:
                charge_summary_cents = max(
                    (item.amount_cents for item in reversals if self._is_charge_refund_summary(item) and item.active),
                    default=0,
                )
                active_refunded_cents = max(
                    charge_summary_cents,
                    legacy_refund_cents,
                )
            refunded_cents = min(
                purchase.amount_eur_cents,
                active_refunded_cents,
            )
            active_dispute_cents = sum(
                item.amount_cents for item in reversals if item.kind == "dispute" and item.active
            )
            active_reversal_cents = min(
                purchase.amount_eur_cents,
                refunded_cents + active_dispute_cents,
            )
            dispute_active = any(item.kind == "dispute" and item.active for item in reversals)
            desired_reversal = math.ceil(
                purchase.credits * active_reversal_cents / purchase.amount_eur_cents,
            )
            current_reversal = int(purchase.reversed_credits or 0)
            fulfilled = purchase.fulfilled_at is not None
            debt_credits = min(
                desired_reversal,
                int(purchase.reversal_debt_credits or 0),
            )

            # The reversal object, purchase aggregate, wallet and audit ledger
            # share this transaction. A crash cannot leave one side committed.
            if fulfilled and purchase.user_id is not None and desired_reversal > current_reversal:
                delta = desired_reversal - current_reversal
                mutation = self.points_store.reverse_paid_purchase_once_in_session(
                    session,
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
                    int(purchase.reversal_debt_credits or 0) + max(0, mutation.debt_delta),
                )
            elif fulfilled and purchase.user_id is not None and desired_reversal < current_reversal:
                delta = current_reversal - desired_reversal
                mutation = self.points_store.restore_paid_reversal_once_in_session(
                    session,
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
                    max(
                        0,
                        int(purchase.reversal_debt_credits or 0) + min(0, mutation.debt_delta),
                    ),
                )
            elif purchase.user_id is None:
                debt_credits = 0

            purchase.refunded_amount_cents = refunded_cents
            purchase.dispute_active = dispute_active
            purchase.reversed_amount_cents = active_reversal_cents
            purchase.reversed_credits = desired_reversal
            purchase.reversal_debt_credits = debt_credits
            purchase.status = self._reversal_status(purchase)
            # A query above can autoflush the purchase after the payment intent is
            # attached. The database trigger may then extend financial retention
            # from the local observation time before SQLAlchemy refreshes this
            # instance. Never follow that with an older provider-derived deadline.
            reversal_retention = financial_retention_deadline(
                max(provider_event_created, now),
            )
            purchase.financial_retention_until = max(
                int(purchase.financial_retention_until),
                reversal_retention,
            )
            invoice = session.scalar(
                select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).with_for_update().limit(1)
            )
            if invoice is not None:
                invoice.financial_retention_until = max(
                    int(invoice.financial_retention_until),
                    reversal_retention,
                )
                invoice.updated_at = max(int(invoice.updated_at), now)
            purchase.updated_at = now

    def _upsert_authoritative_refunds_in_session(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        payment_intent_id: str,
        refunds: tuple[StripeRefundState, ...],
        charge_refunded_amount_cents: int,
        reconciliation_event_id: str,
        reconciliation_event_created: int,
        now: int,
    ) -> None:
        if not refunds:
            raise BillingProviderError(
                "Stripe refund reconciliation returned no refund objects",
            )

        refund_ids = [refund.id for refund in refunds]
        if len(refund_ids) != len(set(refund_ids)):
            raise BillingProviderError(
                "Stripe refund reconciliation returned duplicate objects",
            )

        existing_refunds = list(
            session.scalars(
                select(DbCreditPurchaseReversal)
                .where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                    DbCreditPurchaseReversal.provider == "stripe",
                    DbCreditPurchaseReversal.kind == "refund",
                )
                .with_for_update()
            )
        )
        existing_individuals = {
            item.provider_reversal_id: item for item in existing_refunds if self._is_individual_refund(item)
        }
        missing_refund_ids = set(existing_individuals) - set(refund_ids)
        if missing_refund_ids:
            raise BillingProviderError(
                "Stripe refund reconciliation returned an incomplete refund set",
            )

        active_refund_cents = 0
        for refund in refunds:
            if (
                refund.payment_intent_id != payment_intent_id
                or refund.currency != purchase.currency.lower()
                or refund.amount_cents <= 0
                or refund.amount_cents > purchase.amount_eur_cents
                or refund.status not in (_ACTIVE_REFUND_STATUSES | _INACTIVE_REFUND_STATUSES)
                or refund.created <= 0
            ):
                raise BillingProviderError(
                    "Stripe refund reconciliation returned invalid data",
                )
            is_active = refund.status in _ACTIVE_REFUND_STATUSES
            if is_active:
                active_refund_cents += refund.amount_cents

        if active_refund_cents < charge_refunded_amount_cents:
            raise BillingProviderError(
                "Stripe refund reconciliation returned an incomplete active cumulative refund total",
            )
        if active_refund_cents > purchase.amount_eur_cents:
            raise BillingProviderError(
                "Stripe refund reconciliation exceeds the purchase amount",
            )

        for refund in refunds:
            is_active = refund.status in _ACTIVE_REFUND_STATUSES
            reversal = existing_individuals.get(refund.id)
            if reversal is None:
                reversal = session.scalar(
                    select(DbCreditPurchaseReversal)
                    .where(
                        DbCreditPurchaseReversal.provider == "stripe",
                        DbCreditPurchaseReversal.provider_reversal_id == refund.id,
                    )
                    .with_for_update()
                    .limit(1)
                )
            if reversal is None:
                reversal = DbCreditPurchaseReversal(
                    id=uuid.uuid4().hex,
                    purchase_id=purchase.id,
                    provider="stripe",
                    provider_reversal_id=refund.id,
                    provider_event_id=None,
                    provider_event_created=reconciliation_event_created,
                    kind="refund",
                    amount_cents=refund.amount_cents,
                    currency=refund.currency,
                    status=refund.status,
                    active=is_active,
                    created_at=now,
                    updated_at=now,
                )
                session.add(reversal)
            elif (
                reversal.purchase_id != purchase.id
                or reversal.kind != "refund"
                or reversal.currency.lower() != refund.currency
                or reversal.amount_cents != refund.amount_cents
            ):
                raise BillingValidationError(
                    "Refund object conflicts with its purchase",
                )

            reconciliation_id = hashlib.sha256(
                (f"stripe-refund-reconciliation:{reconciliation_event_id}:{refund.id}").encode()
            ).hexdigest()
            reversal.provider_event_id = f"reconcile_{reconciliation_id}"
            reversal.provider_event_created = max(
                int(reversal.provider_event_created),
                reconciliation_event_created,
            )
            reversal.status = refund.status
            reversal.active = is_active
            reversal.updated_at = now

    @staticmethod
    def _provider_event_created(value: Any) -> int:
        if isinstance(value, bool):
            raise BillingValidationError("Stripe event timestamp is invalid")
        try:
            created = int(value)
        except (TypeError, ValueError) as exc:
            raise BillingValidationError(
                "Stripe event timestamp is invalid",
            ) from exc
        if created <= 0:
            raise BillingValidationError("Stripe event timestamp is invalid")
        return created

    @staticmethod
    def _event_livemode(value: Any) -> bool:
        if not isinstance(value, bool):
            raise BillingValidationError("Stripe event mode is invalid")
        return value

    @staticmethod
    def _validated_event_livemode(
        event_type: str,
        value: Any,
    ) -> bool | None:
        if event_type not in _RECOGNIZED_EVENT_TYPES:
            return value if isinstance(value, bool) else None
        livemode = BillingService._event_livemode(value)
        if livemode != (not settings.is_dev):
            raise BillingValidationError(
                "Stripe event mode does not match the runtime environment",
            )
        return livemode

    @staticmethod
    def _validate_checkout_session_id_mode(session_id: str) -> None:
        if not session_id.startswith(("cs_test_", "cs_live_")):
            raise BillingValidationError("Invalid Checkout Session id")
        expected_prefix = "cs_test_" if settings.is_dev else "cs_live_"
        if not session_id.startswith(expected_prefix):
            raise BillingValidationError(
                "Checkout Session mode does not match the runtime environment",
            )

    @staticmethod
    def _dispute_active(*, event_type: str, status: str) -> bool:
        if event_type == "charge.dispute.funds_withdrawn":
            return True
        if event_type == "charge.dispute.funds_reinstated":
            return False
        return status not in _INACTIVE_DISPUTE_STATUSES

    @staticmethod
    def _newer_cumulative_refund_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event_id: str,
        provider_event_created: int,
        amount_cents: int,
    ) -> bool:
        if amount_cents != reversal.amount_cents:
            return amount_cents > reversal.amount_cents
        if provider_event_created != reversal.provider_event_created:
            return provider_event_created > reversal.provider_event_created
        return event_id > str(reversal.provider_event_id or "")

    @staticmethod
    def _stale_refund_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event_id: str,
        provider_event_created: int,
        status: str,
    ) -> bool:
        if provider_event_created != reversal.provider_event_created:
            return provider_event_created < reversal.provider_event_created
        incoming_rank = _REFUND_STATUS_RANK[status]
        current_rank = _REFUND_STATUS_RANK.get(reversal.status, -1)
        if incoming_rank != current_rank:
            return incoming_rank < current_rank
        return event_id <= str(reversal.provider_event_id or "")

    @staticmethod
    def _is_charge_refund_summary(
        reversal: DbCreditPurchaseReversal,
    ) -> bool:
        return reversal.status == _CHARGE_REFUND_SUMMARY_STATUS or reversal.provider_reversal_id.startswith("ch_")

    @staticmethod
    def _is_individual_refund(
        reversal: DbCreditPurchaseReversal,
    ) -> bool:
        return (
            reversal.provider == "stripe"
            and reversal.provider_reversal_id.startswith("re_")
            and not BillingService._is_charge_refund_summary(reversal)
        )

    @staticmethod
    def _is_legacy_refund_baseline(
        reversal: DbCreditPurchaseReversal,
    ) -> bool:
        return reversal.kind == "refund" and reversal.provider == "legacy_migration"

    @staticmethod
    def _stale_dispute_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event_id: str,
        provider_event_created: int,
        active: bool,
    ) -> bool:
        return provider_event_created < reversal.provider_event_created or (
            provider_event_created == reversal.provider_event_created
            and bool(reversal.active)
            and not active
            and reversal.provider_event_id != event_id
        )

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
                select(DbStripeWebhookEvent).where(DbStripeWebhookEvent.id == event_id).with_for_update().limit(1)
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
                receipt.processed_at = int(time.time()) if status in {"processed", "ignored"} else None

    @staticmethod
    def _validate_fulfillment_object(
        obj: dict[str, Any],
        metadata: dict[str, Any],
        purchase: DbCreditPurchase,
        session_id: str,
        *,
        manual_capture: bool = False,
    ) -> None:
        BillingService._validate_checkout_identity(
            obj,
            metadata,
            purchase,
            session_id,
        )
        payment_intent_id = BillingService._stripe_id(obj.get("payment_intent"))
        payment_status = str(obj.get("payment_status") or "")
        purchase_capture_policy = (
            purchase.snapshot.get("capture_policy") if isinstance(purchase.snapshot, dict) else None
        )
        valid_payment_status = payment_status in {"paid", "unpaid"} if manual_capture else payment_status == "paid"
        valid_capture_policy = (
            purchase_capture_policy == MANUAL_CAPTURE_POLICY
            if manual_capture
            else purchase_capture_policy != MANUAL_CAPTURE_POLICY
        )
        if not payment_intent_id.startswith("pi_") or not valid_payment_status or not valid_capture_policy:
            raise BillingValidationError("Checkout fulfillment does not match purchase snapshot")

    @staticmethod
    def _validate_manual_capture_checkout(
        obj: dict[str, Any],
        metadata: dict[str, Any],
        purchase: DbCreditPurchase,
        session_id: str,
    ) -> None:
        BillingService._validate_checkout_identity(
            obj,
            metadata,
            purchase,
            session_id,
        )
        payment_intent_id = BillingService._stripe_id(
            obj.get("payment_intent"),
        )
        purchase_capture_policy = (
            purchase.snapshot.get("capture_policy") if isinstance(purchase.snapshot, dict) else None
        )
        if (
            purchase_capture_policy != MANUAL_CAPTURE_POLICY
            or not payment_intent_id.startswith("pi_")
            or str(obj.get("payment_status") or "") not in {"paid", "unpaid"}
        ):
            raise BillingValidationError(
                "Checkout authorization does not match purchase snapshot",
            )

    @staticmethod
    def _validate_manual_payment_intent(
        payment_intent: StripePaymentIntentState,
        *,
        purchase: DbCreditPurchase,
        expected_payment_intent_id: str,
        expected_user_id: str,
        allowed_statuses: frozenset[str],
    ) -> None:
        expected_metadata = BillingService._expected_purchase_metadata(
            purchase,
        )
        if (
            payment_intent.id != expected_payment_intent_id
            or payment_intent.status not in allowed_statuses
            or payment_intent.capture_method != "manual"
            or payment_intent.amount_cents != purchase.amount_eur_cents
            or (payment_intent.status == "requires_capture" and payment_intent.amount_received_cents != 0)
            or payment_intent.currency.lower() != purchase.currency.lower()
            or payment_intent.metadata.get("user_id") != expected_user_id
            or any(payment_intent.metadata.get(key) != value for key, value in expected_metadata.items())
        ):
            raise BillingProviderError(
                "Stripe PaymentIntent does not match the authorized purchase",
            )

    def _mark_ineligible_authorization_canceled(
        self,
        purchase_id: str,
    ) -> None:
        with self.db.session() as session:
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise BillingProviderError(
                    "Local Checkout purchase is not available yet",
                )
            if purchase.fulfilled_at is not None:
                raise BillingConflictError(
                    "A fulfilled purchase cannot become ineligible",
                )
            if (
                purchase.payment_intent_id is not None
                or purchase.payment_snapshot is not None
                or purchase.customer_snapshot is not None
                or purchase.tax_snapshot is not None
            ):
                raise BillingConflictError(
                    "Canceled authorization conflicts with financial evidence",
                )
            purchase.status = "failed"
            purchase.error = (
                "Payment authorization canceled: billing details are outside the supported Greece-only payment flow"
            )
            purchase.checkout_url = None
            purchase.updated_at = int(time.time())

    @staticmethod
    def _expected_purchase_metadata(
        purchase: DbCreditPurchase,
    ) -> dict[str, str]:
        expected_metadata = {
            "purchase_id": purchase.id,
            "package_key": purchase.package_key,
            "credits": str(purchase.credits),
            "integration_identifier": purchase.integration_identifier,
            "catalog_version": str(
                purchase.snapshot.get("catalog_version") if isinstance(purchase.snapshot, dict) else ""
            ),
            "billing_country": str(
                purchase.snapshot.get("billing_country") if isinstance(purchase.snapshot, dict) else ""
            ),
            "capture_policy": str(
                purchase.snapshot.get("capture_policy") if isinstance(purchase.snapshot, dict) else ""
            ),
        }
        consumer_contract = purchase.snapshot.get("consumer_contract") if isinstance(purchase.snapshot, dict) else None
        if isinstance(consumer_contract, dict):
            expected_metadata.update(
                {
                    "consumer_disclosure_id": str(
                        consumer_contract.get("disclosure_id") or "",
                    ),
                    "consumer_disclosure_sha256": str(
                        consumer_contract.get("disclosure_sha256") or "",
                    ),
                    "consumer_contract_sha256": str(
                        purchase.snapshot.get(
                            "consumer_contract_sha256",
                        )
                        or "",
                    ),
                    "consumer_locale": str(
                        consumer_contract.get("locale") or "",
                    ),
                }
            )
        else:
            expected_metadata["consumer_contract_sha256"] = ""
        return expected_metadata

    @staticmethod
    def _validate_checkout_identity(
        obj: dict[str, Any],
        metadata: dict[str, Any],
        purchase: DbCreditPurchase,
        session_id: str,
    ) -> None:
        client_reference_id = str(obj.get("client_reference_id") or "")
        metadata_user_id = str(metadata.get("user_id") or "")
        if purchase.user_id is not None:
            account_identity_matches = client_reference_id == purchase.user_id and metadata_user_id == purchase.user_id
        else:
            try:
                account_identity_matches = (
                    bool(client_reference_id)
                    and client_reference_id == metadata_user_id
                    and financial_account_reference_hash(client_reference_id) == purchase.account_reference_hash
                )
            except ValueError:
                account_identity_matches = False
        expected_metadata = BillingService._expected_purchase_metadata(
            purchase,
        )
        if (
            not session_id
            or session_id != purchase.checkout_session_id
            or str(obj.get("status") or "") != "complete"
            or int(obj.get("amount_total") or 0) != purchase.amount_eur_cents
            or str(obj.get("currency") or "").lower() != purchase.currency.lower()
            or not account_identity_matches
            or any(str(metadata.get(key) or "") != value for key, value in expected_metadata.items())
        ):
            raise BillingValidationError("Checkout fulfillment does not match purchase snapshot")

    def _validate_checkout_session(
        self,
        checkout: StripeCheckoutSession,
        purchase: DbCreditPurchase,
    ) -> None:
        parsed = urlparse(checkout.url)
        expected_prefix = "cs_test_" if settings.is_dev else "cs_live_"
        valid = (
            checkout.id.startswith(expected_prefix)
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
        if purchase.user_id is None and purchase.fulfilled_at is not None:
            return "manual_review_account_deleted"
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
        return f"gsubs_credits_{suffix}"

    @staticmethod
    def _stripe_id(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("id") or "")
        return ""
