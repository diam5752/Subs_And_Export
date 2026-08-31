"""Checkout creation, account deletion, and webhook entry operations."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbUser,
)
from backend.app.services.billing_records import (
    GREEK_B2C_BILLING_COUNTRY,
)
from backend.app.services.billing_service_base import BillingServiceMixinBase
from backend.app.services.billing_types import (
    _CHECKOUT_EVENT_TYPES,
    UNPAID_PURCHASE_RETENTION_SECONDS,
    BillingConflictError,
    BillingDisabledError,
    BillingError,
    BillingGateway,
    BillingProviderError,
    BillingValidationError,
    CheckoutResult,
    CreditPackage,
    PurchaseStatus,
    WebhookResult,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    ConsumerContractValidationError,
    build_consumer_contract_snapshot,
    consumer_contract_snapshot_sha256,
)


class BillingCheckoutMixin(BillingServiceMixinBase):
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
            return cast(CheckoutResult, self._checkout_result(purchase))
        if purchase.fulfilled_at is not None:
            return cast(CheckoutResult, self._checkout_result(purchase))
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
        self._assert_no_open_purchase(purchases)
        purchase_ids = [purchase.id for purchase in purchases]
        self._assert_no_pending_withdrawal(session, purchase_ids)
        durable_child_purchase_ids = self._durable_child_purchase_ids(
            session,
            purchase_ids,
        )
        retention_cutoff = max(1, int(time.time()) - 5)
        if any(
            self._deletable_unpaid_purchase(
                purchase,
                retention_cutoff=retention_cutoff,
                durable_child_purchase_ids=durable_child_purchase_ids,
            )
            for purchase in purchases
        ):
            # The database independently validates this transaction-local
            # cutoff against its own clock and every durable child record.
            session.execute(
                text("SELECT set_config('gsubs.billing_retention_cutoff', :cutoff, true)"),
                {"cutoff": str(retention_cutoff)},
            )

        for purchase in purchases:
            purchase.checkout_url = None
            if self._deletable_unpaid_purchase(
                purchase,
                retention_cutoff=retention_cutoff,
                durable_child_purchase_ids=durable_child_purchase_ids,
            ):
                session.delete(purchase)

    @staticmethod
    def _assert_no_open_purchase(purchases: list[DbCreditPurchase]) -> None:
        if any(
            purchase.fulfilled_at is None
            and purchase.payment_snapshot is None
            and purchase.status not in {"expired", "failed"}
            for purchase in purchases
        ):
            raise BillingConflictError(
                "Account deletion is blocked while a payment is still open",
            )

    @staticmethod
    def _assert_no_pending_withdrawal(
        session: Session,
        purchase_ids: list[str],
    ) -> None:
        if not purchase_ids:
            return
        pending_withdrawal = session.scalar(
            select(DbBillingWithdrawalRequest)
            .where(
                DbBillingWithdrawalRequest.purchase_id.in_(purchase_ids),
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

    @staticmethod
    def _durable_child_purchase_ids(
        session: Session,
        purchase_ids: list[str],
    ) -> set[str]:
        if not purchase_ids:
            return set()
        result: set[str] = set()
        for purchase_id_column in (
            DbBillingInvoice.purchase_id,
            DbCreditPurchaseReversal.purchase_id,
            DbBillingContractConfirmation.purchase_id,
            DbBillingWithdrawalRequest.purchase_id,
            DbBillingAdjustmentRecord.purchase_id,
            DbBillingWithdrawalResolution.purchase_id,
        ):
            result.update(
                session.scalars(
                    select(purchase_id_column).where(
                        purchase_id_column.in_(purchase_ids),
                    )
                )
            )
        return result

    @staticmethod
    def _deletable_unpaid_purchase(
        purchase: DbCreditPurchase,
        *,
        retention_cutoff: int,
        durable_child_purchase_ids: set[str],
    ) -> bool:
        is_financial_record = (
            purchase.fulfilled_at is not None
            or purchase.payment_snapshot is not None
            or purchase.payment_intent_id is not None
        )
        return (
            not is_financial_record
            and purchase.status in {"expired", "failed"}
            and purchase.financial_retention_until <= retention_cutoff
            and purchase.id not in durable_child_purchase_ids
        )

    def _lock_account_billing(self, session: Session, user_id: str) -> None:
        lock_key = self._advisory_lock_key(
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
                payload=payload,
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
        if not settings.paid_credit_checkout_enabled or not self._consumer_contract_registry_is_approved():
            raise BillingDisabledError("Credit purchases are not enabled yet")
        if self._gateway is None:
            self._gateway = self._stripe_gateway_factory()
        return self._gateway

    def _webhook_gateway(self) -> BillingGateway:
        """Keep signed reconciliation active even when new sales are paused."""
        if self._gateway is None:
            self._gateway = self._stripe_gateway_factory()
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
                expected_catalog_version=self._catalog_version(),
                accepted_at=now,
            )
        except ConsumerContractValidationError as exc:
            raise BillingValidationError(str(exc)) from exc
        snapshot = {
            "catalog_version": self._catalog_version(),
            "package_key": package.key,
            "credits": package.credits,
            "amount_eur_cents": package.amount_eur_cents,
            "currency": "eur",
            "stripe_price_id": package.price_id,
            "billing_country": billing_country,
            "capture_policy": self._manual_capture_policy(),
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
                    expected_catalog_version=self._catalog_version(),
                    accepted_at=recorded_accepted_at,
                )
            except ConsumerContractValidationError as exc:
                raise BillingValidationError(str(exc)) from exc
            expected_snapshot = {
                "catalog_version": self._catalog_version(),
                "package_key": package.key,
                "credits": package.credits,
                "amount_eur_cents": package.amount_eur_cents,
                "currency": "eur",
                "stripe_price_id": package.price_id,
                "billing_country": billing_country,
                "capture_policy": self._manual_capture_policy(),
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
