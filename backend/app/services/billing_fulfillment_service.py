"""Stripe event processing and credit fulfillment operations."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbCreditPurchase,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordConflictError,
    BillingConsumerRecordValidationError,
    new_contract_confirmation,
    verify_contract_confirmation,
)
from backend.app.services.billing_records import (
    CheckoutAccountingIneligibleError,
    PaidFinancialRecord,
    PaymentCaptureEvidence,
    build_paid_financial_record,
    new_pending_invoice,
    validate_checkout_accounting_eligibility,
)
from backend.app.services.billing_service_base import BillingServiceMixinBase
from backend.app.services.billing_types import (
    _RECOGNIZED_EVENT_TYPES,
    _REVERSAL_EVENT_TYPES,
    BillingConflictError,
    BillingProviderError,
    BillingValidationError,
    _StripeEventScope,
)
from backend.app.services.points import make_idempotency_id


class BillingFulfillmentMixin(BillingServiceMixinBase):
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
            self._process_checkout_completion(
                obj,
                purchase_id=event_scope.purchase_id,
                provider_event_created=provider_event_created,
                livemode=livemode,
            )
            return "processed"
        if event_type == "checkout.session.async_payment_succeeded":
            self._process_async_checkout_success(
                obj,
                purchase_id=event_scope.purchase_id,
                provider_event_created=provider_event_created,
                livemode=livemode,
            )
            return "processed"
        if event_type == "checkout.session.expired":
            self._expire_checkout(obj)
            return "processed"
        if event_type == "checkout.session.async_payment_failed":
            self._fail_async_checkout(obj)
            return "processed"
        if event_type in _REVERSAL_EVENT_TYPES:
            self._process_reversal_event(
                obj,
                event_id=event_id,
                event_type=event_type,
                event_scope=event_scope,
                provider_event_created=provider_event_created,
            )
            return "processed"
        return "ignored"

    def _process_checkout_completion(
        self,
        obj: dict[str, Any],
        *,
        purchase_id: str | None,
        provider_event_created: Any,
        livemode: Any,
    ) -> None:
        if self._manual_capture_required(purchase_id=purchase_id, obj=obj):
            self._capture_and_fulfill_checkout(
                obj,
                purchase_id=purchase_id,
                provider_event_created=self._provider_event_created(provider_event_created),
                livemode=self._event_livemode(livemode),
            )
            return
        if str(obj.get("payment_status") or "") == "unpaid":
            self._await_checkout_payment(obj, purchase_id=purchase_id)
            return
        self._fulfill_checkout(
            obj,
            purchase_id=purchase_id,
            provider_event_created=self._provider_event_created(provider_event_created),
            livemode=self._event_livemode(livemode),
        )

    def _process_async_checkout_success(
        self,
        obj: dict[str, Any],
        *,
        purchase_id: str | None,
        provider_event_created: Any,
        livemode: Any,
    ) -> None:
        if self._manual_capture_required(purchase_id=purchase_id, obj=obj):
            raise BillingValidationError(
                "Manual-capture Checkout cannot use asynchronous fulfillment",
            )
        self._fulfill_checkout(
            obj,
            purchase_id=purchase_id,
            provider_event_created=self._provider_event_created(provider_event_created),
            livemode=self._event_livemode(livemode),
        )

    def _process_reversal_event(
        self,
        obj: dict[str, Any],
        *,
        event_id: str,
        event_type: str,
        event_scope: _StripeEventScope,
        provider_event_created: Any,
    ) -> None:
        validated_created = self._provider_event_created(provider_event_created)
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
            provider_event_created=validated_created,
        )

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
                    return purchase.snapshot.get("capture_policy") == self._manual_capture_policy()
        metadata = obj.get("metadata")
        return isinstance(metadata, dict) and metadata.get("capture_policy") == self._manual_capture_policy()

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

        if self._reconcile_canceled_authorization(authorized, purchase_id=purchase.id):
            return
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
                capture_policy=self._manual_capture_policy(),
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
            purchase = self._locked_fulfillment_purchase(session, purchase_id)
            self._validate_fulfillment_object(
                obj,
                metadata,
                purchase,
                session_id,
                manual_capture=capture_evidence is not None,
            )
            if purchase.fulfilled_at is not None:
                return
            financial_record = self._paid_financial_record(
                purchase=purchase,
                checkout=obj,
                provider_event_created=provider_event_created,
                livemode=livemode,
                capture_evidence=capture_evidence,
            )
            self._store_paid_financial_snapshots(purchase, financial_record)
            self._ensure_pending_invoice(
                session,
                purchase=purchase,
                financial_record=financial_record,
                provider_event_created=provider_event_created,
            )
            purchase.financial_retention_until = max(
                int(purchase.financial_retention_until),
                financial_record.retention_until,
            )
            self._attach_fulfillment_payment_intent(
                purchase,
                self._stripe_id(obj.get("payment_intent")),
            )
            self._ensure_contract_confirmation(
                session,
                purchase=purchase,
                provider_event_created=provider_event_created,
            )
            self._complete_paid_fulfillment(session, purchase)

    @staticmethod
    def _locked_fulfillment_purchase(
        session: Session,
        purchase_id: str,
    ) -> DbCreditPurchase:
        purchase = session.scalar(
            select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
        )
        if purchase is None:
            raise BillingProviderError(
                "Local Checkout purchase is not available yet",
            )
        return purchase

    @staticmethod
    def _paid_financial_record(
        *,
        purchase: DbCreditPurchase,
        checkout: dict[str, Any],
        provider_event_created: int,
        livemode: bool,
        capture_evidence: PaymentCaptureEvidence | None,
    ) -> PaidFinancialRecord:
        try:
            return build_paid_financial_record(
                purchase=purchase,
                checkout=checkout,
                stripe_event_created=provider_event_created,
                livemode=livemode,
                capture_evidence=capture_evidence,
            )
        except ValueError as exc:
            raise BillingValidationError(str(exc)) from exc

    @staticmethod
    def _store_paid_financial_snapshots(
        purchase: DbCreditPurchase,
        financial_record: PaidFinancialRecord,
    ) -> None:
        existing_snapshots = (
            purchase.payment_snapshot,
            purchase.customer_snapshot,
            purchase.tax_snapshot,
        )
        if all(snapshot is None for snapshot in existing_snapshots):
            purchase.payment_snapshot = financial_record.payment_snapshot
            purchase.customer_snapshot = financial_record.customer_snapshot
            purchase.tax_snapshot = financial_record.tax_snapshot
            return
        if any(snapshot is None for snapshot in existing_snapshots):
            raise BillingConflictError(
                "Paid checkout financial snapshots are incomplete",
            )
        expected_snapshots = (
            financial_record.payment_snapshot,
            financial_record.customer_snapshot,
            financial_record.tax_snapshot,
        )
        if existing_snapshots != expected_snapshots:
            raise BillingConflictError(
                "Paid checkout financial snapshots conflict with signed Checkout evidence",
            )

    @staticmethod
    def _ensure_pending_invoice(
        session: Session,
        *,
        purchase: DbCreditPurchase,
        financial_record: PaidFinancialRecord,
        provider_event_created: int,
    ) -> None:
        expected = new_pending_invoice(
            purchase_id=purchase.id,
            record=financial_record,
            created_at=provider_event_created,
        )
        invoices = tuple(
            session.scalars(
                select(DbBillingInvoice)
                .where(
                    (DbBillingInvoice.purchase_id == purchase.id) | (DbBillingInvoice.id == expected.id),
                )
                .with_for_update()
                .limit(2)
            )
        )
        if len(invoices) > 1:
            raise BillingConflictError(
                "Paid checkout invoice identity is ambiguous",
            )
        if not invoices:
            session.add(expected)
            return
        if not BillingFulfillmentMixin._pending_invoices_match(invoices[0], expected):
            raise BillingConflictError(
                "Paid checkout invoice conflicts with signed Checkout evidence",
            )

    @staticmethod
    def _pending_invoices_match(
        invoice: DbBillingInvoice,
        expected: DbBillingInvoice,
    ) -> bool:
        return (
            invoice.id,
            invoice.purchase_id,
            invoice.provider,
            invoice.document_kind,
            invoice.document_status,
            invoice.aade_document_type,
            invoice.aade_series,
            invoice.aade_aa,
            invoice.aade_mark,
            invoice.issued_at,
            invoice.recorded_by_user_id,
            invoice.recorded_at,
            invoice.document_snapshot,
            invoice.financial_retention_until,
            invoice.created_at,
            invoice.updated_at,
        ) == (
            expected.id,
            expected.purchase_id,
            expected.provider,
            expected.document_kind,
            expected.document_status,
            expected.aade_document_type,
            expected.aade_series,
            expected.aade_aa,
            expected.aade_mark,
            expected.issued_at,
            expected.recorded_by_user_id,
            expected.recorded_at,
            expected.document_snapshot,
            expected.financial_retention_until,
            expected.created_at,
            expected.updated_at,
        )

    @staticmethod
    def _attach_fulfillment_payment_intent(
        purchase: DbCreditPurchase,
        payment_intent_id: str,
    ) -> None:
        if purchase.payment_intent_id not in {None, payment_intent_id}:
            raise BillingValidationError(
                "Checkout PaymentIntent conflicts with its purchase",
            )
        purchase.payment_intent_id = payment_intent_id

    @staticmethod
    def _ensure_contract_confirmation(
        session: Session,
        *,
        purchase: DbCreditPurchase,
        provider_event_created: int,
    ) -> None:
        confirmation = session.scalar(
            select(DbBillingContractConfirmation)
            .where(DbBillingContractConfirmation.purchase_id == purchase.id)
            .limit(1)
        )
        if confirmation is None:
            try:
                confirmation = new_contract_confirmation(
                    purchase=purchase,
                    contract_concluded_at=provider_event_created,
                    generated_at=int(time.time()),
                )
            except BillingConsumerRecordValidationError as exc:
                raise BillingValidationError(str(exc)) from exc
            session.add(confirmation)
            # Durable contract evidence is flushed in the same transaction before
            # any paid credits can be granted.
            session.flush()
        try:
            verify_contract_confirmation(confirmation, purchase=purchase)
        except BillingConsumerRecordConflictError as exc:
            raise BillingConflictError(str(exc)) from exc

    def _complete_paid_fulfillment(
        self,
        session: Session,
        purchase: DbCreditPurchase,
    ) -> None:
        now = int(time.time())
        purchase.updated_at = now
        purchase_user_id = purchase.user_id
        if purchase_user_id is None:
            purchase.fulfilled_at = now
            purchase.status = "manual_review_account_deleted"
            purchase.error = "Paid Checkout completed after account deletion"
            purchase.checkout_url = None
            return
        credits_to_grant = max(0, purchase.credits - purchase.reversed_credits)
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
