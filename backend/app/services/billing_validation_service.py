"""Webhook receipt, purchase validation, and result helpers."""

from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app.core.config import settings
from backend.app.db.models import (
    DbCreditPurchase,
    DbStripeWebhookEvent,
)
from backend.app.services.billing_service_base import BillingServiceMixinBase
from backend.app.services.billing_types import (
    _IDEMPOTENCY_RE,
    _INTEGRATION_ALPHABET,
    BillingConflictError,
    BillingDisabledError,
    BillingProviderError,
    BillingValidationError,
    CheckoutResult,
    CreditPackage,
    StripeCheckoutSession,
    StripePaymentIntentState,
)
from backend.app.services.billing_webhook_fingerprint import (
    legacy_webhook_hash_matches_pending_count,
    stripe_webhook_payload_fingerprint,
)
from backend.app.services.financial_records import (
    financial_account_reference_hash,
)


class BillingValidationMixin(BillingServiceMixinBase):
    def _claim_webhook_event(
        self,
        *,
        event_id: str,
        event_type: str,
        payload: bytes,
    ) -> bool:
        payload_hash = stripe_webhook_payload_fingerprint(payload)
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
            if receipt.event_type != event_type:
                raise BillingConflictError("Stripe event id was replayed with different data")
            if receipt.payload_sha256 != payload_hash:
                if not legacy_webhook_hash_matches_pending_count(
                    payload,
                    receipt.payload_sha256,
                ):
                    raise BillingConflictError(
                        "Stripe event id was replayed with different data",
                    )
                receipt.payload_sha256 = payload_hash
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

    def _validate_fulfillment_object(
        self,
        obj: dict[str, Any],
        metadata: dict[str, Any],
        purchase: DbCreditPurchase,
        session_id: str,
        *,
        manual_capture: bool = False,
    ) -> None:
        self._validate_checkout_identity(
            obj,
            metadata,
            purchase,
            session_id,
        )
        payment_intent_id = self._stripe_id(obj.get("payment_intent"))
        payment_status = str(obj.get("payment_status") or "")
        purchase_capture_policy = (
            purchase.snapshot.get("capture_policy") if isinstance(purchase.snapshot, dict) else None
        )
        valid_payment_status = payment_status in {"paid", "unpaid"} if manual_capture else payment_status == "paid"
        valid_capture_policy = (
            purchase_capture_policy == self._manual_capture_policy()
            if manual_capture
            else purchase_capture_policy != self._manual_capture_policy()
        )
        if not payment_intent_id.startswith("pi_") or not valid_payment_status or not valid_capture_policy:
            raise BillingValidationError("Checkout fulfillment does not match purchase snapshot")

    def _validate_manual_capture_checkout(
        self,
        obj: dict[str, Any],
        metadata: dict[str, Any],
        purchase: DbCreditPurchase,
        session_id: str,
    ) -> None:
        self._validate_checkout_identity(
            obj,
            metadata,
            purchase,
            session_id,
        )
        payment_intent_id = self._stripe_id(
            obj.get("payment_intent"),
        )
        purchase_capture_policy = (
            purchase.snapshot.get("capture_policy") if isinstance(purchase.snapshot, dict) else None
        )
        if (
            purchase_capture_policy != self._manual_capture_policy()
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
        expected_metadata = BillingValidationMixin._expected_purchase_metadata(
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
        self._mark_canceled_authorization(
            purchase_id,
            error=(
                "Payment authorization canceled: billing details are outside the supported Greece-only payment flow"
            ),
        )

    def _reconcile_canceled_authorization(
        self,
        payment_intent: StripePaymentIntentState,
        *,
        purchase_id: str,
    ) -> bool:
        if payment_intent.status != "canceled":
            return False
        if payment_intent.amount_received_cents != 0:
            raise BillingProviderError(
                "Canceled Stripe authorization reports received funds",
            )
        self._mark_canceled_authorization(
            purchase_id,
            error="Payment authorization was canceled before capture",
        )
        return True

    def _mark_canceled_authorization(
        self,
        purchase_id: str,
        *,
        error: str,
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
            purchase.error = error
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
        expected_metadata = BillingValidationMixin._expected_purchase_metadata(
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

    def _package(self, package_key: str) -> CreditPackage:
        normalized = package_key.strip().lower()
        for package in self._credit_packages():
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
