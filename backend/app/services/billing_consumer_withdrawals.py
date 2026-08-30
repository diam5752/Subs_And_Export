"""Withdrawal submission and authenticated record access operations."""

from __future__ import annotations

import time
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_consumer_contracts import (
    _EMAIL_RE,
    _WITHDRAWAL_SCHEMA_VERSION_V1,
    _WITHDRAWAL_V1_STATUS,
    _WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS,
    WITHDRAWAL_SCHEMA_VERSION,
    BillingConsumerRecordConflictError,
    BillingConsumerRecordNotFoundError,
    BillingConsumerRecordValidationError,
    WithdrawalResult,
    _canonical_json_bytes,
    _deterministic_id,
    _sha256,
    verify_contract_confirmation,
)
from backend.app.services.billing_manual_records import BillingManualRecordError
from backend.app.services.billing_manual_records import (
    verify_withdrawal_resolution as verify_manual_withdrawal_resolution,
)
from backend.app.services.financial_records import financial_retention_deadline


def _validated_withdrawal_request_intent(locale: str, withdrawal_requested: bool) -> None:
    if locale not in {"el", "en"}:
        raise BillingConsumerRecordValidationError("Unsupported withdrawal locale")
    if type(withdrawal_requested) is not bool or withdrawal_requested is not True:
        raise BillingConsumerRecordValidationError("An express withdrawal request is required")


def _normalized_withdrawal_customer(
    confirmed_name: str,
    confirmation_email: str,
) -> tuple[str, str]:
    normalized_name = confirmed_name.strip()
    normalized_email = confirmation_email.strip()
    if normalized_name != confirmed_name or not normalized_name or len(normalized_name) > 100:
        raise BillingConsumerRecordValidationError("Confirmed customer name is invalid")
    if (
        normalized_email != confirmation_email
        or len(normalized_email) > 255
        or not _EMAIL_RE.fullmatch(normalized_email)
    ):
        raise BillingConsumerRecordValidationError("Confirmation email is invalid")
    return normalized_name, normalized_email


def _validated_withdrawal_received_at(submitted_at: int | None) -> int:
    received_at = int(time.time()) if submitted_at is None else submitted_at
    if isinstance(received_at, bool) or received_at <= 0:
        raise BillingConsumerRecordValidationError("Withdrawal timestamp is invalid")
    return received_at


def _withdrawal_acknowledgement_bytes(
    request_snapshot: dict[str, Any],
    *,
    request_sha256: str,
    receipt_notice: str,
) -> bytes:
    return _canonical_json_bytes(
        {
            **request_snapshot,
            "document_type": "gsubs_withdrawal_acknowledgement",
            "request_sha256": request_sha256,
            "receipt_notice": receipt_notice,
        },
        pretty=True,
    )


def _new_withdrawal_record(
    *,
    purchase: DbCreditPurchase,
    confirmation: DbBillingContractConfirmation,
    normalized_key: str,
    locale: str,
    received_at: int,
    request_snapshot: dict[str, Any],
    request_bytes: bytes,
    request_sha256: str,
    acknowledgement_bytes: bytes,
) -> DbBillingWithdrawalRequest:
    return DbBillingWithdrawalRequest(
        id=_deterministic_id("gsubs-withdrawal", f"{purchase.id}:{received_at}"),
        purchase_id=purchase.id,
        idempotency_key=normalized_key,
        schema_version=_WITHDRAWAL_SCHEMA_VERSION_V1,
        locale=locale,
        status=_WITHDRAWAL_V1_STATUS,
        request_snapshot=request_snapshot,
        request_bytes=request_bytes,
        request_sha256=request_sha256,
        submitted_at=received_at,
        acknowledgement_mime_type="application/json; charset=utf-8",
        acknowledgement_filename=f"gsubs-withdrawal-{purchase.id}.json",
        acknowledgement_bytes=acknowledgement_bytes,
        acknowledgement_sha256=_sha256(acknowledgement_bytes),
        available_at=received_at,
        financial_retention_until=max(
            confirmation.financial_retention_until,
            financial_retention_deadline(received_at),
        ),
        created_at=received_at,
    )


class BillingConsumerWithdrawalMixin:
    """Withdrawal operations shared by the public record-store facade."""

    db: Database

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def submit_withdrawal(
        self,
        *,
        user_id: str,
        purchase_id: str,
        idempotency_key: str,
        locale: str,
        withdrawal_requested: bool,
        confirmed_name: str,
        confirmation_email: str,
        submitted_at: int | None = None,
    ) -> WithdrawalResult:
        normalized_key, normalized_name, normalized_email, received_at = self._validated_withdrawal_submission(
            idempotency_key=idempotency_key,
            locale=locale,
            withdrawal_requested=withdrawal_requested,
            confirmed_name=confirmed_name,
            confirmation_email=confirmation_email,
            submitted_at=submitted_at,
        )
        with self.db.session() as session:
            self._lock_withdrawal_idempotency(session, normalized_key)
            replay = self._withdrawal_replay_by_key(
                session,
                normalized_key=normalized_key,
                user_id=user_id,
                purchase_id=purchase_id,
                locale=locale,
                normalized_name=normalized_name,
                normalized_email=normalized_email,
            )
            if replay is not None:
                return replay
            purchase, confirmation = self._locked_withdrawal_purchase(
                session,
                user_id=user_id,
                purchase_id=purchase_id,
            )
            replay = self._withdrawal_replay_for_purchase(
                session,
                purchase=purchase,
                confirmation=confirmation,
                locale=locale,
                normalized_name=normalized_name,
                normalized_email=normalized_email,
            )
            if replay is not None:
                return replay
            withdrawal = self._new_withdrawal_request(
                purchase=purchase,
                confirmation=confirmation,
                normalized_key=normalized_key,
                locale=locale,
                normalized_name=normalized_name,
                normalized_email=normalized_email,
                received_at=received_at,
            )
            session.add(withdrawal)
            session.flush()
            return cast(
                WithdrawalResult,
                self._withdrawal_result(
                    withdrawal,
                    purchase=purchase,
                    confirmation=confirmation,
                ),
            )

    def _validated_withdrawal_submission(
        self,
        *,
        idempotency_key: str,
        locale: str,
        withdrawal_requested: bool,
        confirmed_name: str,
        confirmation_email: str,
        submitted_at: int | None,
    ) -> tuple[str, str, str, int]:
        normalized_key = self._validate_idempotency_key(idempotency_key)
        _validated_withdrawal_request_intent(locale, withdrawal_requested)
        normalized_name, normalized_email = _normalized_withdrawal_customer(confirmed_name, confirmation_email)
        received_at = _validated_withdrawal_received_at(submitted_at)
        return normalized_key, normalized_name, normalized_email, received_at

    def _lock_withdrawal_idempotency(
        self,
        session: Session,
        normalized_key: str,
    ) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {
                "lock_key": self._advisory_lock_key(
                    f"billing-withdrawal:{normalized_key}",
                )
            },
        )

    def _withdrawal_replay_by_key(
        self,
        session: Session,
        *,
        normalized_key: str,
        user_id: str,
        purchase_id: str,
        locale: str,
        normalized_name: str,
        normalized_email: str,
    ) -> WithdrawalResult | None:
        existing = session.scalar(
            select(DbBillingWithdrawalRequest)
            .where(DbBillingWithdrawalRequest.idempotency_key == normalized_key)
            .limit(1)
        )
        if existing is None:
            return None
        purchase = session.get(DbCreditPurchase, existing.purchase_id)
        if purchase is None or purchase.user_id != user_id or existing.purchase_id != purchase_id:
            raise BillingConsumerRecordConflictError(
                "Idempotency key was used for another withdrawal request",
            )
        confirmation = self._withdrawal_confirmation(session, purchase)
        self._assert_withdrawal_replay_equivalent(
            existing,
            purchase=purchase,
            confirmation=confirmation,
            locale=locale,
            normalized_name=normalized_name,
            normalized_email=normalized_email,
            conflict_message="Idempotency key was used for another withdrawal request",
        )
        return cast(
            WithdrawalResult,
            self._withdrawal_result(
                existing,
                purchase=purchase,
                confirmation=confirmation,
            ),
        )

    def _locked_withdrawal_purchase(
        self,
        session: Session,
        *,
        user_id: str,
        purchase_id: str,
    ) -> tuple[DbCreditPurchase, DbBillingContractConfirmation]:
        purchase = session.scalar(
            select(DbCreditPurchase)
            .where(
                DbCreditPurchase.id == purchase_id,
                DbCreditPurchase.user_id == user_id,
            )
            .with_for_update()
            .limit(1)
        )
        if purchase is None:
            raise BillingConsumerRecordNotFoundError("Purchase not found")
        confirmation = self._withdrawal_confirmation(session, purchase)
        verify_contract_confirmation(confirmation, purchase=purchase)
        return purchase, confirmation

    @staticmethod
    def _withdrawal_confirmation(
        session: Session,
        purchase: DbCreditPurchase,
    ) -> DbBillingContractConfirmation:
        confirmation = session.scalar(
            select(DbBillingContractConfirmation)
            .where(DbBillingContractConfirmation.purchase_id == purchase.id)
            .limit(1)
        )
        if confirmation is None:
            raise BillingConsumerRecordConflictError(
                "The purchase has no concluded contract confirmation",
            )
        return confirmation

    def _withdrawal_replay_for_purchase(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        confirmation: DbBillingContractConfirmation,
        locale: str,
        normalized_name: str,
        normalized_email: str,
    ) -> WithdrawalResult | None:
        existing = session.scalar(
            select(DbBillingWithdrawalRequest).where(DbBillingWithdrawalRequest.purchase_id == purchase.id).limit(1)
        )
        if existing is None:
            return None
        self._assert_withdrawal_replay_equivalent(
            existing,
            purchase=purchase,
            confirmation=confirmation,
            locale=locale,
            normalized_name=normalized_name,
            normalized_email=normalized_email,
            conflict_message="A withdrawal request already exists for this purchase with different details",
        )
        return cast(
            WithdrawalResult,
            self._withdrawal_result(
                existing,
                purchase=purchase,
                confirmation=confirmation,
            ),
        )

    def _new_withdrawal_request(
        self,
        *,
        purchase: DbCreditPurchase,
        confirmation: DbBillingContractConfirmation,
        normalized_key: str,
        locale: str,
        normalized_name: str,
        normalized_email: str,
        received_at: int,
    ) -> DbBillingWithdrawalRequest:
        if WITHDRAWAL_SCHEMA_VERSION != _WITHDRAWAL_SCHEMA_VERSION_V1:
            raise BillingConsumerRecordValidationError(
                "Withdrawal acknowledgement schema version is unsupported",
            )
        request_snapshot = self._withdrawal_request_snapshot(
            purchase=purchase,
            confirmation=confirmation,
            locale=locale,
            normalized_name=normalized_name,
            normalized_email=normalized_email,
            received_at=received_at,
        )
        request_bytes = _canonical_json_bytes(request_snapshot)
        request_sha256 = _sha256(request_bytes)
        acknowledgement_bytes = _withdrawal_acknowledgement_bytes(
            request_snapshot,
            request_sha256=request_sha256,
            receipt_notice=self._receipt_notice(locale),
        )
        return _new_withdrawal_record(
            purchase=purchase,
            confirmation=confirmation,
            normalized_key=normalized_key,
            locale=locale,
            received_at=received_at,
            request_snapshot=request_snapshot,
            request_bytes=request_bytes,
            request_sha256=request_sha256,
            acknowledgement_bytes=acknowledgement_bytes,
        )

    def _withdrawal_request_snapshot(
        self,
        *,
        purchase: DbCreditPurchase,
        confirmation: DbBillingContractConfirmation,
        locale: str,
        normalized_name: str,
        normalized_email: str,
        received_at: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": _WITHDRAWAL_SCHEMA_VERSION_V1,
            "request_type": "consumer_contract_withdrawal",
            "purchase_id": purchase.id,
            "locale": locale,
            "statement": self._withdrawal_statement(locale, purchase_id=purchase.id),
            "confirmed_name": normalized_name,
            "confirmation_electronic_means": {
                "type": "email",
                "address": normalized_email,
                "delivery_status": "not_sent_transactional_channel_not_ready",
            },
            "submitted_at": received_at,
            "contract_concluded_at": confirmation.contract_concluded_at,
            "timeliness_assessment_status": _WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS,
            "status": _WITHDRAWAL_V1_STATUS,
            "automatic_stripe_refund_executed": False,
            "automatic_aade_adjustment_executed": False,
        }

    def get_withdrawal_acknowledgement(
        self,
        *,
        user_id: str,
        purchase_id: str,
    ) -> DbBillingWithdrawalRequest:
        with self.db.session() as session:
            owned_record = session.execute(
                select(
                    DbBillingWithdrawalRequest,
                    DbCreditPurchase,
                    DbBillingContractConfirmation,
                )
                .join(
                    DbCreditPurchase,
                    DbCreditPurchase.id == DbBillingWithdrawalRequest.purchase_id,
                )
                .join(
                    DbBillingContractConfirmation,
                    DbBillingContractConfirmation.purchase_id == DbBillingWithdrawalRequest.purchase_id,
                )
                .where(
                    DbBillingWithdrawalRequest.purchase_id == purchase_id,
                    DbCreditPurchase.user_id == user_id,
                )
                .limit(1)
            ).one_or_none()
        if owned_record is None:
            raise BillingConsumerRecordNotFoundError(
                "Withdrawal acknowledgement not found",
            )
        withdrawal, purchase, confirmation = owned_record
        self._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
        return cast(DbBillingWithdrawalRequest, withdrawal)

    def get_withdrawal_resolution(
        self,
        *,
        user_id: str,
        purchase_id: str,
    ) -> DbBillingWithdrawalResolution:
        with self.db.session() as session:
            owned_record = session.execute(
                select(
                    DbBillingWithdrawalResolution,
                    DbBillingWithdrawalRequest,
                    DbCreditPurchase,
                )
                .join(
                    DbBillingWithdrawalRequest,
                    DbBillingWithdrawalRequest.id == DbBillingWithdrawalResolution.withdrawal_id,
                )
                .join(
                    DbCreditPurchase,
                    DbCreditPurchase.id == DbBillingWithdrawalResolution.purchase_id,
                )
                .where(
                    DbBillingWithdrawalResolution.purchase_id == purchase_id,
                    DbCreditPurchase.user_id == user_id,
                )
                .limit(1)
            ).one_or_none()
            if owned_record is None:
                raise BillingConsumerRecordNotFoundError(
                    "Withdrawal resolution not found",
                )
            resolution, withdrawal, purchase = owned_record
            adjustment = (
                session.get(
                    DbBillingAdjustmentRecord,
                    resolution.adjustment_id,
                )
                if resolution.adjustment_id is not None
                else None
            )
            reversal = (
                session.get(
                    DbCreditPurchaseReversal,
                    adjustment.reversal_id,
                )
                if adjustment is not None
                else None
            )
            try:
                verify_manual_withdrawal_resolution(
                    resolution,
                    withdrawal=withdrawal,
                    purchase=purchase,
                    adjustment=adjustment,
                    reversal=reversal,
                )
            except BillingManualRecordError as exc:
                raise BillingConsumerRecordConflictError(
                    "Withdrawal resolution evidence is invalid",
                ) from exc
            return cast(DbBillingWithdrawalResolution, resolution)
