"""Prepaid video-credit Checkout and replay-safe Stripe fulfillment."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.services import pricing
from backend.app.services.billing_records import (
    GREEK_B2C_BILLING_COUNTRY,
)
from backend.app.services.billing_records import (
    MANUAL_CAPTURE_POLICY as MANUAL_CAPTURE_POLICY,
)
from backend.app.services.billing_types import (
    _ACTIVE_REFUND_STATUSES as _ACTIVE_REFUND_STATUSES,
)
from backend.app.services.billing_types import (
    _INACTIVE_REFUND_STATUSES as _INACTIVE_REFUND_STATUSES,
)
from backend.app.services.billing_types import (
    CATALOG_VERSION as CATALOG_VERSION,
)
from backend.app.services.billing_types import (
    STRIPE_API_VERSION as STRIPE_API_VERSION,
)
from backend.app.services.billing_types import (
    UNPAID_PURCHASE_RETENTION_SECONDS as UNPAID_PURCHASE_RETENTION_SECONDS,
)
from backend.app.services.billing_types import (
    BillingConflictError as BillingConflictError,
)
from backend.app.services.billing_types import (
    BillingDisabledError as BillingDisabledError,
)
from backend.app.services.billing_types import (
    BillingError as BillingError,
)
from backend.app.services.billing_types import (
    BillingGateway as BillingGateway,
)
from backend.app.services.billing_types import (
    BillingProviderError as BillingProviderError,
)
from backend.app.services.billing_types import (
    BillingValidationError as BillingValidationError,
)
from backend.app.services.billing_types import (
    CheckoutResult as CheckoutResult,
)
from backend.app.services.billing_types import (
    CreditPackage as CreditPackage,
)
from backend.app.services.billing_types import (
    PurchaseStatus as PurchaseStatus,
)
from backend.app.services.billing_types import (
    StripeCheckoutSession as StripeCheckoutSession,
)
from backend.app.services.billing_types import (
    StripePaymentIntentState as StripePaymentIntentState,
)
from backend.app.services.billing_types import (
    StripeRefundState as StripeRefundState,
)
from backend.app.services.billing_types import (
    WebhookResult as WebhookResult,
)
from backend.app.services.consumer_contracts import (
    consumer_contract_registry_is_approved as consumer_contract_registry_is_approved,
)
from backend.app.services.consumer_contracts import (
    public_consumer_contract,
)
from backend.app.services.points import PointsStore

_STRIPE_PERMISSION_PROBE_PAYMENT_INTENT_ID = "pi_gsubs_permission_probe_absent"
_STRIPE_PERMISSION_PROBE_IDEMPOTENCY_KEY = "gsubs-permission-probe-payment-intent-write-v1"


def _checkout_metadata(
    *,
    purchase_id: str,
    user_id: str,
    package_key: str,
    credits: int,
    integration_identifier: str,
    consumer_disclosure_id: str,
    consumer_disclosure_sha256: str,
    consumer_contract_sha256: str,
    consumer_locale: str,
) -> dict[str, str]:
    return {
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
        metadata = _checkout_metadata(
            purchase_id=purchase_id,
            user_id=user_id,
            package_key=package_key,
            credits=credits,
            integration_identifier=integration_identifier,
            consumer_disclosure_id=consumer_disclosure_id,
            consumer_disclosure_sha256=consumer_disclosure_sha256,
            consumer_contract_sha256=consumer_contract_sha256,
            consumer_locale=consumer_locale,
        )
        session = self._client.v1.checkout.sessions.create(
            {
                "mode": "payment",
                "submit_type": "pay",
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

    def assert_payment_intent_write_access(self) -> None:
        """Prove capture access with a provider ID that can never be real."""
        try:
            self._client.v1.payment_intents.capture(
                _STRIPE_PERMISSION_PROBE_PAYMENT_INTENT_ID,
                {},
                {
                    "idempotency_key": (_STRIPE_PERMISSION_PROBE_IDEMPOTENCY_KEY),
                },
            )
        except self._stripe.PermissionError as exc:
            raise BillingDisabledError(
                "Stripe restricted key lacks Payment Intents Write access",
            ) from exc
        except self._stripe.InvalidRequestError as exc:
            if getattr(exc, "http_status", None) == 404 and getattr(exc, "code", None) == "resource_missing":
                return
            raise BillingProviderError(
                "Stripe Payment Intents Write access check failed",
            ) from exc
        except Exception as exc:
            raise BillingProviderError(
                "Stripe Payment Intents Write access check is temporarily unavailable",
            ) from exc
        raise BillingProviderError(
            "Stripe Payment Intents permission probe unexpectedly resolved",
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


from backend.app.services.billing_checkout_service import BillingCheckoutMixin
from backend.app.services.billing_fulfillment_service import BillingFulfillmentMixin
from backend.app.services.billing_refund_service import BillingRefundMixin
from backend.app.services.billing_reversal_service import BillingReversalMixin
from backend.app.services.billing_validation_service import BillingValidationMixin

__all__ = [
    "CATALOG_VERSION",
    "STRIPE_API_VERSION",
    "UNPAID_PURCHASE_RETENTION_SECONDS",
    "BillingConflictError",
    "BillingDisabledError",
    "BillingError",
    "BillingGateway",
    "BillingProviderError",
    "BillingService",
    "BillingValidationError",
    "CheckoutResult",
    "CreditPackage",
    "PurchaseStatus",
    "StripeCheckoutSession",
    "StripePaymentIntentState",
    "StripeRefundState",
    "StripeSdkGateway",
    "WebhookResult",
    "credit_packages",
    "public_credit_catalog",
]


class BillingService(
    BillingCheckoutMixin,
    BillingFulfillmentMixin,
    BillingReversalMixin,
    BillingRefundMixin,
    BillingValidationMixin,
):
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
