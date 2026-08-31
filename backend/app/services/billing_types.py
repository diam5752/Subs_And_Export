"""Billing constants, errors, gateway protocol, and public value objects."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.services.points import PointsBalance

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
