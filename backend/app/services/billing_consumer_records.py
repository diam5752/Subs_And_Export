"""Immutable consumer-contract confirmations and withdrawal acknowledgements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
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
    _IDEMPOTENCY_RE,
    _WITHDRAWAL_SCHEMA_VERSION_V1,
    _canonical_json_bytes,
    _sha256,
)
from backend.app.services.billing_consumer_contracts import (
    WITHDRAWAL_SCHEMA_VERSION as WITHDRAWAL_SCHEMA_VERSION,
)
from backend.app.services.billing_consumer_contracts import (
    BillingConsumerRecordConflictError as BillingConsumerRecordConflictError,
)
from backend.app.services.billing_consumer_contracts import (
    BillingConsumerRecordError as BillingConsumerRecordError,
)
from backend.app.services.billing_consumer_contracts import (
    BillingConsumerRecordNotFoundError as BillingConsumerRecordNotFoundError,
)
from backend.app.services.billing_consumer_contracts import (
    BillingConsumerRecordValidationError as BillingConsumerRecordValidationError,
)
from backend.app.services.billing_consumer_contracts import (
    BillingPurchaseSummary as BillingPurchaseSummary,
)
from backend.app.services.billing_consumer_contracts import (
    WithdrawalResult as WithdrawalResult,
)
from backend.app.services.billing_consumer_contracts import (
    new_contract_confirmation as new_contract_confirmation,
)
from backend.app.services.billing_consumer_contracts import (
    verify_contract_confirmation as verify_contract_confirmation,
)
from backend.app.services.billing_consumer_withdrawals import (
    BillingConsumerWithdrawalMixin,
)
from backend.app.services.billing_manual_records import (
    BillingManualRecordError,
    WithdrawalResolutionDecision,
)
from backend.app.services.billing_manual_records import (
    verify_withdrawal_resolution as verify_manual_withdrawal_resolution,
)
from backend.app.services.billing_withdrawal_validation import (
    validate_withdrawal_identity as _validate_withdrawal_identity,
)
from backend.app.services.billing_withdrawal_validation import (
    validated_withdrawal_concluded_at as _validated_withdrawal_concluded_at,
)

__all__ = [
    "WITHDRAWAL_SCHEMA_VERSION",
    "BillingConsumerRecordConflictError",
    "BillingConsumerRecordError",
    "BillingConsumerRecordNotFoundError",
    "BillingConsumerRecordStore",
    "BillingConsumerRecordValidationError",
    "BillingPurchaseSummary",
    "WithdrawalResult",
    "new_contract_confirmation",
    "verify_contract_confirmation",
    "verify_withdrawal_record",
]


@dataclass(frozen=True, slots=True)
class _PurchaseEvidence:
    purchases: tuple[DbCreditPurchase, ...]
    confirmations: dict[str, DbBillingContractConfirmation]
    withdrawals: dict[str, DbBillingWithdrawalRequest]
    resolutions: dict[str, DbBillingWithdrawalResolution]
    adjustments: dict[str, DbBillingAdjustmentRecord]
    reversals: dict[str, DbCreditPurchaseReversal]


def _purchase_confirmations(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, DbBillingContractConfirmation]:
    return {
        confirmation.purchase_id: confirmation
        for confirmation in session.scalars(
            select(DbBillingContractConfirmation).where(
                DbBillingContractConfirmation.purchase_id.in_(purchase_ids),
            )
        )
    }


def _purchase_withdrawals(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, DbBillingWithdrawalRequest]:
    return {
        withdrawal.purchase_id: withdrawal
        for withdrawal in session.scalars(
            select(DbBillingWithdrawalRequest).where(DbBillingWithdrawalRequest.purchase_id.in_(purchase_ids))
        )
    }


def _purchase_resolutions(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, DbBillingWithdrawalResolution]:
    return {
        resolution.purchase_id: resolution
        for resolution in session.scalars(
            select(DbBillingWithdrawalResolution).where(
                DbBillingWithdrawalResolution.purchase_id.in_(purchase_ids),
            )
        )
    }


def _resolution_adjustments(
    session: Session,
    resolutions: dict[str, DbBillingWithdrawalResolution],
) -> dict[str, DbBillingAdjustmentRecord]:
    adjustment_ids = [
        resolution.adjustment_id for resolution in resolutions.values() if resolution.adjustment_id is not None
    ]
    return {
        adjustment.id: adjustment
        for adjustment in session.scalars(
            select(DbBillingAdjustmentRecord).where(DbBillingAdjustmentRecord.id.in_(adjustment_ids))
        )
    }


def _adjustment_reversals(
    session: Session,
    adjustments: dict[str, DbBillingAdjustmentRecord],
) -> dict[str, DbCreditPurchaseReversal]:
    reversal_ids = [adjustment.reversal_id for adjustment in adjustments.values()]
    return {
        reversal.id: reversal
        for reversal in session.scalars(
            select(DbCreditPurchaseReversal).where(DbCreditPurchaseReversal.id.in_(reversal_ids))
        )
    }


def _load_purchase_evidence(*, db: Database, user_id: str) -> _PurchaseEvidence:
    with db.session() as session:
        purchases = tuple(
            session.scalars(
                select(DbCreditPurchase)
                .where(DbCreditPurchase.user_id == user_id)
                .order_by(DbCreditPurchase.created_at.desc(), DbCreditPurchase.id.desc())
            )
        )
        purchase_ids = [purchase.id for purchase in purchases]
        if not purchase_ids:
            return _PurchaseEvidence(purchases, {}, {}, {}, {}, {})
        confirmations = _purchase_confirmations(session, purchase_ids)
        withdrawals = _purchase_withdrawals(session, purchase_ids)
        resolutions = _purchase_resolutions(session, purchase_ids)
        adjustments = _resolution_adjustments(session, resolutions)
        reversals = _adjustment_reversals(session, adjustments)
    return _PurchaseEvidence(purchases, confirmations, withdrawals, resolutions, adjustments, reversals)


def _validate_purchase_evidence(purchase: DbCreditPurchase, evidence: _PurchaseEvidence) -> None:
    confirmation = evidence.confirmations.get(purchase.id)
    withdrawal = evidence.withdrawals.get(purchase.id)
    resolution = evidence.resolutions.get(purchase.id)
    if confirmation is not None:
        verify_contract_confirmation(confirmation, purchase=purchase)
    if withdrawal is not None:
        BillingConsumerRecordStore._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
    if resolution is not None:
        _validate_purchase_resolution(
            purchase=purchase,
            withdrawal=withdrawal,
            resolution=resolution,
            evidence=evidence,
        )


def _validate_purchase_resolution(
    *,
    purchase: DbCreditPurchase,
    withdrawal: DbBillingWithdrawalRequest | None,
    resolution: DbBillingWithdrawalResolution,
    evidence: _PurchaseEvidence,
) -> None:
    if withdrawal is None:
        raise BillingConsumerRecordConflictError("Withdrawal resolution request is unavailable")
    adjustment = evidence.adjustments.get(resolution.adjustment_id) if resolution.adjustment_id is not None else None
    reversal = evidence.reversals.get(adjustment.reversal_id) if adjustment is not None else None
    try:
        verify_manual_withdrawal_resolution(
            resolution,
            withdrawal=withdrawal,
            purchase=purchase,
            adjustment=adjustment,
            reversal=reversal,
        )
    except BillingManualRecordError as exc:
        raise BillingConsumerRecordConflictError("Withdrawal resolution evidence is invalid") from exc


def _purchase_summary(purchase: DbCreditPurchase, evidence: _PurchaseEvidence) -> BillingPurchaseSummary:
    confirmation = evidence.confirmations.get(purchase.id)
    withdrawal = evidence.withdrawals.get(purchase.id)
    resolution = evidence.resolutions.get(purchase.id)
    return BillingPurchaseSummary(
        purchase_id=purchase.id,
        package_key=purchase.package_key,
        credits=purchase.credits,
        amount_eur_cents=purchase.amount_eur_cents,
        currency=purchase.currency.lower(),
        status=purchase.status,
        created_at=purchase.created_at,
        fulfilled_at=purchase.fulfilled_at,
        contract_confirmation_available=confirmation is not None,
        contract_concluded_at=confirmation.contract_concluded_at if confirmation is not None else None,
        withdrawal_action_available=confirmation is not None and withdrawal is None,
        withdrawal_status=(
            resolution.decision if resolution is not None else (withdrawal.status if withdrawal is not None else None)
        ),
        withdrawal_acknowledgement_available=withdrawal is not None,
        withdrawal_resolution_available=resolution is not None,
        withdrawal_resolution_decision=(
            cast(WithdrawalResolutionDecision, resolution.decision) if resolution is not None else None
        ),
    )


def _build_purchase_summaries(evidence: _PurchaseEvidence) -> tuple[BillingPurchaseSummary, ...]:
    summaries: list[BillingPurchaseSummary] = []
    for purchase in evidence.purchases:
        _validate_purchase_evidence(purchase, evidence)
        summaries.append(_purchase_summary(purchase, evidence))
    return tuple(summaries)


def _withdrawal_request_snapshot(withdrawal: DbBillingWithdrawalRequest) -> dict[str, Any]:
    snapshot = withdrawal.request_snapshot
    if not isinstance(snapshot, dict):
        raise BillingConsumerRecordConflictError("Withdrawal request snapshot is invalid")
    return snapshot


def _normalized_withdrawal_idempotency_key(withdrawal: DbBillingWithdrawalRequest) -> str:
    try:
        return BillingConsumerRecordStore._validate_idempotency_key(withdrawal.idempotency_key)
    except (AttributeError, BillingConsumerRecordValidationError) as exc:
        raise BillingConsumerRecordConflictError("Withdrawal acknowledgement identity is invalid") from exc


def _validate_withdrawal_digests(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    request_snapshot: dict[str, Any],
) -> None:
    request_bytes = _canonical_json_bytes(request_snapshot)
    if (
        not isinstance(withdrawal.request_bytes, bytes)
        or withdrawal.request_bytes != request_bytes
        or _sha256(withdrawal.request_bytes) != withdrawal.request_sha256
        or not isinstance(withdrawal.acknowledgement_bytes, bytes)
        or _sha256(withdrawal.acknowledgement_bytes) != withdrawal.acknowledgement_sha256
    ):
        raise BillingConsumerRecordConflictError("Withdrawal acknowledgement digest does not match")


def _validate_withdrawal_acknowledgement(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    request_snapshot: dict[str, Any],
    receipt_notice: str,
) -> None:
    try:
        acknowledgement = json.loads(withdrawal.acknowledgement_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingConsumerRecordConflictError("Withdrawal acknowledgement content is invalid") from exc
    expected_acknowledgement = {
        **request_snapshot,
        "document_type": "gsubs_withdrawal_acknowledgement",
        "request_sha256": withdrawal.request_sha256,
        "receipt_notice": receipt_notice,
    }
    if (
        not isinstance(acknowledgement, dict)
        or acknowledgement != expected_acknowledgement
        or withdrawal.acknowledgement_bytes != _canonical_json_bytes(expected_acknowledgement, pretty=True)
    ):
        raise BillingConsumerRecordConflictError("Withdrawal acknowledgement conflicts with request evidence")


def _validate_withdrawal_external_evidence(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    concluded_at: int,
    purchase: DbCreditPurchase | None,
    confirmation: DbBillingContractConfirmation | None,
) -> None:
    if confirmation is not None:
        if purchase is None:
            raise BillingConsumerRecordConflictError("Withdrawal purchase evidence is unavailable")
        verify_contract_confirmation(confirmation, purchase=purchase)
        if (
            confirmation.purchase_id != withdrawal.purchase_id
            or concluded_at != confirmation.contract_concluded_at
            or withdrawal.financial_retention_until < confirmation.financial_retention_until
        ):
            raise BillingConsumerRecordConflictError("Withdrawal conflicts with contract confirmation")
    if purchase is not None and purchase.id != withdrawal.purchase_id:
        raise BillingConsumerRecordConflictError("Withdrawal conflicts with purchase evidence")


class BillingConsumerRecordStore(BillingConsumerWithdrawalMixin):
    """Authenticated access and idempotent receipt of withdrawal requests."""

    def __init__(self, *, db: Database) -> None:
        self.db = db

    def get_contract_confirmation(
        self,
        *,
        user_id: str,
        purchase_id: str,
    ) -> DbBillingContractConfirmation:
        with self.db.session() as session:
            owned_record = session.execute(
                select(
                    DbBillingContractConfirmation,
                    DbCreditPurchase,
                )
                .join(
                    DbCreditPurchase,
                    DbCreditPurchase.id == DbBillingContractConfirmation.purchase_id,
                )
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase_id,
                    DbCreditPurchase.user_id == user_id,
                )
                .limit(1)
            ).one_or_none()
        if owned_record is None:
            raise BillingConsumerRecordNotFoundError(
                "Contract confirmation not found",
            )
        confirmation, purchase = owned_record
        verify_contract_confirmation(
            confirmation,
            purchase=purchase,
        )
        return cast(DbBillingContractConfirmation, confirmation)

    def list_purchases(
        self,
        *,
        user_id: str,
    ) -> tuple[BillingPurchaseSummary, ...]:
        return _build_purchase_summaries(_load_purchase_evidence(db=self.db, user_id=user_id))

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if normalized != value or not _IDEMPOTENCY_RE.fullmatch(normalized):
            raise BillingConsumerRecordValidationError(
                "Invalid Idempotency-Key",
            )
        return normalized

    @staticmethod
    def _advisory_lock_key(value: str) -> int:
        return int.from_bytes(
            hashlib.sha256(value.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )

    @staticmethod
    def _verify_withdrawal(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase | None = None,
        confirmation: DbBillingContractConfirmation | None = None,
    ) -> None:
        if (purchase is None) != (confirmation is None):
            raise BillingConsumerRecordConflictError(
                "Withdrawal purchase or contract evidence is unavailable",
            )
        if type(withdrawal.schema_version) is int and withdrawal.schema_version == _WITHDRAWAL_SCHEMA_VERSION_V1:
            BillingConsumerRecordStore._verify_withdrawal_v1(
                withdrawal,
                purchase=purchase,
                confirmation=confirmation,
            )
            return
        raise BillingConsumerRecordConflictError(
            "Withdrawal acknowledgement schema version is unsupported",
        )

    @staticmethod
    def _verify_withdrawal_v1(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase | None = None,
        confirmation: DbBillingContractConfirmation | None = None,
    ) -> None:
        request_snapshot = _withdrawal_request_snapshot(withdrawal)
        normalized_key = _normalized_withdrawal_idempotency_key(withdrawal)
        _validate_withdrawal_digests(withdrawal, request_snapshot=request_snapshot)
        _validate_withdrawal_identity(withdrawal, normalized_idempotency_key=normalized_key)
        concluded_at = _validated_withdrawal_concluded_at(
            withdrawal,
            request_snapshot=request_snapshot,
            expected_statement=BillingConsumerRecordStore._withdrawal_statement_v1(
                withdrawal.locale,
                purchase_id=withdrawal.purchase_id,
            ),
        )
        _validate_withdrawal_acknowledgement(
            withdrawal,
            request_snapshot=request_snapshot,
            receipt_notice=BillingConsumerRecordStore._receipt_notice_v1(withdrawal.locale),
        )
        _validate_withdrawal_external_evidence(
            withdrawal,
            concluded_at=concluded_at,
            purchase=purchase,
            confirmation=confirmation,
        )

    @staticmethod
    def _withdrawal_result(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase | None = None,
        confirmation: DbBillingContractConfirmation | None = None,
    ) -> WithdrawalResult:
        BillingConsumerRecordStore._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
        return WithdrawalResult(
            withdrawal_id=withdrawal.id,
            purchase_id=withdrawal.purchase_id,
            status=withdrawal.status,
            submitted_at=withdrawal.submitted_at,
            timeliness_assessment_status=str(
                withdrawal.request_snapshot.get(
                    "timeliness_assessment_status",
                    "",
                ),
            ),
            acknowledgement_sha256=withdrawal.acknowledgement_sha256,
        )

    @staticmethod
    def _assert_withdrawal_replay_equivalent(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase,
        confirmation: DbBillingContractConfirmation,
        locale: str,
        normalized_name: str,
        normalized_email: str,
        conflict_message: str,
    ) -> None:
        BillingConsumerRecordStore._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
        request_snapshot = withdrawal.request_snapshot
        if (
            withdrawal.purchase_id != purchase.id
            or confirmation.purchase_id != purchase.id
            or withdrawal.locale != locale
            or request_snapshot.get("locale") != locale
            or request_snapshot.get("statement")
            != BillingConsumerRecordStore._withdrawal_statement_v1(
                locale,
                purchase_id=purchase.id,
            )
            or request_snapshot.get("confirmed_name") != normalized_name
            or request_snapshot.get("confirmation_electronic_means")
            != {
                "type": "email",
                "address": normalized_email,
                "delivery_status": ("not_sent_transactional_channel_not_ready"),
            }
            or request_snapshot.get("contract_concluded_at") != confirmation.contract_concluded_at
        ):
            raise BillingConsumerRecordConflictError(conflict_message)

    @staticmethod
    def _withdrawal_statement(locale: str, *, purchase_id: str) -> str:
        if WITHDRAWAL_SCHEMA_VERSION != _WITHDRAWAL_SCHEMA_VERSION_V1:
            raise BillingConsumerRecordValidationError(
                "Withdrawal acknowledgement schema version is unsupported",
            )
        return BillingConsumerRecordStore._withdrawal_statement_v1(
            locale,
            purchase_id=purchase_id,
        )

    @staticmethod
    def _withdrawal_statement_v1(
        locale: str,
        *,
        purchase_id: str,
    ) -> str:
        if locale == "el":
            return f"Δηλώνω ότι υπαναχωρώ από τη σύμβαση αγοράς GSUBS credits με αναγνωριστικό {purchase_id}."
        return f"I give notice that I withdraw from the GSUBS credit purchase contract identified by {purchase_id}."

    @staticmethod
    def _receipt_notice(locale: str) -> str:
        if WITHDRAWAL_SCHEMA_VERSION != _WITHDRAWAL_SCHEMA_VERSION_V1:
            raise BillingConsumerRecordValidationError(
                "Withdrawal acknowledgement schema version is unsupported",
            )
        return BillingConsumerRecordStore._receipt_notice_v1(locale)

    @staticmethod
    def _receipt_notice_v1(locale: str) -> str:
        if locale == "el":
            return (
                "Το αίτημα παραλήφθηκε και εκκρεμεί χειροκίνητη εξέταση. Δεν "
                "εκτελέστηκε αυτόματα επιστροφή Stripe ή διόρθωση ΑΑΔΕ."
            )
        return (
            "The request was received and is pending manual review. No Stripe "
            "refund or AADE adjustment was executed automatically."
        )


def verify_withdrawal_record(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    purchase: DbCreditPurchase,
    confirmation: DbBillingContractConfirmation,
) -> None:
    """Public strict validator shared by account access and GDPR export."""
    BillingConsumerRecordStore._verify_withdrawal(
        withdrawal,
        purchase=purchase,
        confirmation=confirmation,
    )
