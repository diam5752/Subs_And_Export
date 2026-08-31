"""Durable billing records for the GDPR account export."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from .billing_consumer_records import (
    BillingConsumerRecordConflictError,
    verify_contract_confirmation,
    verify_withdrawal_record,
)
from .billing_manual_records import (
    BillingManualRecordError,
    verify_billing_adjustment_record,
    verify_withdrawal_resolution,
)

_BillingPurchaseRow = tuple[DbCreditPurchase, DbBillingInvoice | None]


@dataclass(frozen=True)
class _BillingEvidence:
    reversal_exports_by_purchase: dict[str, list[dict[str, Any]]]
    reversals_by_id: dict[str, DbCreditPurchaseReversal]
    confirmations_by_purchase: dict[str, DbBillingContractConfirmation]
    withdrawals_by_purchase: dict[str, DbBillingWithdrawalRequest]
    adjustments_by_purchase: dict[str, list[DbBillingAdjustmentRecord]]
    resolutions_by_purchase: dict[str, DbBillingWithdrawalResolution]


def _serialize_reversal(reversal: DbCreditPurchaseReversal) -> dict[str, Any]:
    return {
        "id": reversal.id,
        "purchase_id": reversal.purchase_id,
        "provider": reversal.provider,
        "provider_reversal_id": reversal.provider_reversal_id,
        "provider_event_id": reversal.provider_event_id,
        "provider_event_created": reversal.provider_event_created,
        "kind": reversal.kind,
        "amount_cents": reversal.amount_cents,
        "currency": reversal.currency,
        "status": reversal.status,
        "active": reversal.active,
        "created_at": reversal.created_at,
        "updated_at": reversal.updated_at,
    }


def _load_reversals(
    session: Session,
    purchase_ids: list[str],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, DbCreditPurchaseReversal],
]:
    reversal_rows = session.scalars(
        select(DbCreditPurchaseReversal)
        .where(DbCreditPurchaseReversal.purchase_id.in_(purchase_ids))
        .order_by(
            DbCreditPurchaseReversal.provider_event_created.asc(),
            DbCreditPurchaseReversal.created_at.asc(),
            DbCreditPurchaseReversal.id.asc(),
        )
    ).all()
    exports_by_purchase: dict[str, list[dict[str, Any]]] = {}
    for reversal in reversal_rows:
        exports_by_purchase.setdefault(reversal.purchase_id, []).append(_serialize_reversal(reversal))
    return exports_by_purchase, {row.id: row for row in reversal_rows}


def _load_confirmations(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, DbBillingContractConfirmation]:
    rows = session.scalars(
        select(DbBillingContractConfirmation)
        .where(DbBillingContractConfirmation.purchase_id.in_(purchase_ids))
        .order_by(
            DbBillingContractConfirmation.created_at.asc(),
            DbBillingContractConfirmation.id.asc(),
        )
    ).all()
    return {row.purchase_id: row for row in rows}


def _load_withdrawals(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, DbBillingWithdrawalRequest]:
    rows = session.scalars(
        select(DbBillingWithdrawalRequest)
        .where(DbBillingWithdrawalRequest.purchase_id.in_(purchase_ids))
        .order_by(
            DbBillingWithdrawalRequest.submitted_at.asc(),
            DbBillingWithdrawalRequest.id.asc(),
        )
    ).all()
    return {row.purchase_id: row for row in rows}


def _load_adjustments(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, list[DbBillingAdjustmentRecord]]:
    rows = session.scalars(
        select(DbBillingAdjustmentRecord)
        .where(DbBillingAdjustmentRecord.purchase_id.in_(purchase_ids))
        .order_by(
            DbBillingAdjustmentRecord.recorded_at.asc(),
            DbBillingAdjustmentRecord.id.asc(),
        )
    ).all()
    adjustments_by_purchase: dict[str, list[DbBillingAdjustmentRecord]] = {}
    for adjustment in rows:
        adjustments_by_purchase.setdefault(adjustment.purchase_id, []).append(adjustment)
    return adjustments_by_purchase


def _load_resolutions(
    session: Session,
    purchase_ids: list[str],
) -> dict[str, DbBillingWithdrawalResolution]:
    rows = session.scalars(
        select(DbBillingWithdrawalResolution)
        .where(DbBillingWithdrawalResolution.purchase_id.in_(purchase_ids))
        .order_by(
            DbBillingWithdrawalResolution.resolved_at.asc(),
            DbBillingWithdrawalResolution.id.asc(),
        )
    ).all()
    return {row.purchase_id: row for row in rows}


def _empty_billing_evidence() -> _BillingEvidence:
    return _BillingEvidence(
        reversal_exports_by_purchase={},
        reversals_by_id={},
        confirmations_by_purchase={},
        withdrawals_by_purchase={},
        adjustments_by_purchase={},
        resolutions_by_purchase={},
    )


def _load_billing_evidence(
    session: Session,
    purchase_ids: list[str],
) -> _BillingEvidence:
    if not purchase_ids:
        return _empty_billing_evidence()
    reversal_exports, reversals_by_id = _load_reversals(session, purchase_ids)
    return _BillingEvidence(
        reversal_exports_by_purchase=reversal_exports,
        reversals_by_id=reversals_by_id,
        confirmations_by_purchase=_load_confirmations(session, purchase_ids),
        withdrawals_by_purchase=_load_withdrawals(session, purchase_ids),
        adjustments_by_purchase=_load_adjustments(session, purchase_ids),
        resolutions_by_purchase=_load_resolutions(session, purchase_ids),
    )


def _verify_adjustments(
    purchase: DbCreditPurchase,
    adjustments: list[DbBillingAdjustmentRecord],
    reversals_by_id: dict[str, DbCreditPurchaseReversal],
) -> None:
    for adjustment in adjustments:
        reversal = reversals_by_id.get(adjustment.reversal_id)
        if reversal is None:
            raise BillingManualRecordError("AADE adjustment Stripe evidence is unavailable")
        verify_billing_adjustment_record(
            adjustment,
            purchase=purchase,
            reversal=reversal,
        )


def _resolution_adjustment(
    resolution: DbBillingWithdrawalResolution,
    adjustments: list[DbBillingAdjustmentRecord],
) -> DbBillingAdjustmentRecord | None:
    if resolution.adjustment_id is None:
        return None
    return next(
        (item for item in adjustments if item.id == resolution.adjustment_id),
        None,
    )


def _verify_resolution(
    resolution: DbBillingWithdrawalResolution | None,
    *,
    withdrawal: DbBillingWithdrawalRequest | None,
    purchase: DbCreditPurchase,
    adjustments: list[DbBillingAdjustmentRecord],
    reversals_by_id: dict[str, DbCreditPurchaseReversal],
) -> None:
    if resolution is None:
        return
    if withdrawal is None:
        raise BillingManualRecordError("Withdrawal resolution request is unavailable")
    adjustment = _resolution_adjustment(resolution, adjustments)
    reversal = reversals_by_id.get(adjustment.reversal_id) if adjustment is not None else None
    verify_withdrawal_resolution(
        resolution,
        withdrawal=withdrawal,
        purchase=purchase,
        adjustment=adjustment,
        reversal=reversal,
    )


def _verify_purchase_evidence(
    purchase: DbCreditPurchase,
    evidence: _BillingEvidence,
) -> None:
    confirmation = evidence.confirmations_by_purchase.get(purchase.id)
    withdrawal = evidence.withdrawals_by_purchase.get(purchase.id)
    adjustments = evidence.adjustments_by_purchase.get(purchase.id, [])
    if confirmation is not None:
        verify_contract_confirmation(confirmation, purchase=purchase)
    if withdrawal is not None:
        if confirmation is None:
            raise BillingConsumerRecordConflictError("Withdrawal contract confirmation is unavailable")
        verify_withdrawal_record(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
    _verify_adjustments(purchase, adjustments, evidence.reversals_by_id)
    _verify_resolution(
        evidence.resolutions_by_purchase.get(purchase.id),
        withdrawal=withdrawal,
        purchase=purchase,
        adjustments=adjustments,
        reversals_by_id=evidence.reversals_by_id,
    )


def _verify_billing_integrity(
    billing_rows: list[_BillingPurchaseRow],
    evidence: _BillingEvidence,
) -> None:
    try:
        for purchase, _invoice in billing_rows:
            _verify_purchase_evidence(purchase, evidence)
    except (
        BillingConsumerRecordConflictError,
        BillingManualRecordError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Billing export is unavailable because durable billing record integrity validation failed."),
        ) from exc


def _serialize_adjustment(adjustment: DbBillingAdjustmentRecord) -> dict[str, Any]:
    return {
        "id": adjustment.id,
        "reversal_id": adjustment.reversal_id,
        "schema_version": adjustment.schema_version,
        "provider": adjustment.provider,
        "document_kind": adjustment.document_kind,
        "aade_document_type": adjustment.aade_document_type,
        "aade_series": adjustment.aade_series,
        "aade_aa": adjustment.aade_aa,
        "aade_mark": adjustment.aade_mark,
        "issued_at": adjustment.issued_at,
        "amount_cents": adjustment.amount_cents,
        "currency": adjustment.currency,
        "recorded_at": adjustment.recorded_at,
        "document_snapshot": adjustment.document_snapshot,
        "financial_retention_until": adjustment.financial_retention_until,
    }


def _serialize_confirmation(
    confirmation: DbBillingContractConfirmation | None,
) -> dict[str, Any] | None:
    if confirmation is None:
        return None
    return {
        "id": confirmation.id,
        "schema_version": confirmation.schema_version,
        "locale": confirmation.locale,
        "contract_concluded_at": confirmation.contract_concluded_at,
        "mime_type": confirmation.mime_type,
        "filename": confirmation.filename,
        "content": confirmation.content_bytes.decode("utf-8"),
        "content_sha256": confirmation.content_sha256,
        "consumer_contract_sha256": confirmation.consumer_contract_sha256,
        "delivery_channel": confirmation.delivery_channel,
        "delivery_status": confirmation.delivery_status,
        "available_at": confirmation.available_at,
        "financial_retention_until": confirmation.financial_retention_until,
    }


def _serialize_withdrawal(
    withdrawal: DbBillingWithdrawalRequest | None,
) -> dict[str, Any] | None:
    if withdrawal is None:
        return None
    return {
        "id": withdrawal.id,
        "schema_version": withdrawal.schema_version,
        "locale": withdrawal.locale,
        "status": withdrawal.status,
        "request_snapshot": withdrawal.request_snapshot,
        "request_sha256": withdrawal.request_sha256,
        "submitted_at": withdrawal.submitted_at,
        "acknowledgement_mime_type": withdrawal.acknowledgement_mime_type,
        "acknowledgement_filename": withdrawal.acknowledgement_filename,
        "acknowledgement": withdrawal.acknowledgement_bytes.decode("utf-8"),
        "acknowledgement_sha256": withdrawal.acknowledgement_sha256,
        "available_at": withdrawal.available_at,
        "financial_retention_until": withdrawal.financial_retention_until,
    }


def _serialize_resolution(
    resolution: DbBillingWithdrawalResolution | None,
) -> dict[str, Any] | None:
    if resolution is None:
        return None
    return {
        "id": resolution.id,
        "withdrawal_id": resolution.withdrawal_id,
        "schema_version": resolution.schema_version,
        "locale": resolution.locale,
        "decision": resolution.decision,
        "reason_code": resolution.reason_code,
        "adjustment_id": resolution.adjustment_id,
        "resolution": resolution.resolution_bytes.decode("utf-8"),
        "resolution_sha256": resolution.resolution_sha256,
        "resolved_at": resolution.resolved_at,
        "available_at": resolution.available_at,
        "financial_retention_until": resolution.financial_retention_until,
    }


def _serialize_invoice(invoice: DbBillingInvoice | None) -> dict[str, Any] | None:
    if invoice is None:
        return None
    return {
        "id": invoice.id,
        "provider": invoice.provider,
        "document_kind": invoice.document_kind,
        "document_status": invoice.document_status,
        "aade_document_type": invoice.aade_document_type,
        "aade_series": invoice.aade_series,
        "aade_aa": invoice.aade_aa,
        "aade_mark": invoice.aade_mark,
        "issued_at": invoice.issued_at,
        "document_snapshot": invoice.document_snapshot,
        "financial_retention_until": invoice.financial_retention_until,
    }


def _serialize_purchase(
    purchase: DbCreditPurchase,
    invoice: DbBillingInvoice | None,
    evidence: _BillingEvidence,
) -> dict[str, Any]:
    return {
        "id": purchase.id,
        "provider": purchase.provider,
        "status": purchase.status,
        "created_at": purchase.created_at,
        "fulfilled_at": purchase.fulfilled_at,
        "refunded_amount_cents": purchase.refunded_amount_cents,
        "dispute_active": purchase.dispute_active,
        "reversed_amount_cents": purchase.reversed_amount_cents,
        "reversed_credits": purchase.reversed_credits,
        "reversal_debt_credits": purchase.reversal_debt_credits,
        "financial_retention_until": purchase.financial_retention_until,
        "package_snapshot": purchase.snapshot,
        "payment_snapshot": purchase.payment_snapshot,
        "customer_snapshot": purchase.customer_snapshot,
        "tax_snapshot": purchase.tax_snapshot,
        "reversals": evidence.reversal_exports_by_purchase.get(purchase.id, []),
        "aade_adjustment_records": [
            _serialize_adjustment(adjustment) for adjustment in evidence.adjustments_by_purchase.get(purchase.id, [])
        ],
        "contract_confirmation": _serialize_confirmation(evidence.confirmations_by_purchase.get(purchase.id)),
        "withdrawal_request": _serialize_withdrawal(evidence.withdrawals_by_purchase.get(purchase.id)),
        "withdrawal_resolution": _serialize_resolution(evidence.resolutions_by_purchase.get(purchase.id)),
        "invoice": _serialize_invoice(invoice),
    }


def build_billing_purchases(session: Session, user_id: str) -> list[dict[str, Any]]:
    """Load, validate, and serialize durable billing records for one account."""
    billing_rows: list[_BillingPurchaseRow] = [
        (purchase, invoice)
        for purchase, invoice in session.execute(
            select(DbCreditPurchase, DbBillingInvoice)
            .outerjoin(
                DbBillingInvoice,
                DbBillingInvoice.purchase_id == DbCreditPurchase.id,
            )
            .where(DbCreditPurchase.user_id == user_id)
            .order_by(
                DbCreditPurchase.created_at.asc(),
                DbCreditPurchase.id.asc(),
            )
        ).all()
    ]
    purchase_ids = [purchase.id for purchase, _invoice in billing_rows]
    evidence = _load_billing_evidence(session, purchase_ids)
    _verify_billing_integrity(billing_rows, evidence)
    return [_serialize_purchase(purchase, invoice, evidence) for purchase, invoice in billing_rows]
