"""Bounded cleanup for unpaid attempts and expired statutory billing records."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import JSON, and_, delete, func, or_, select, text

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)

_TERMINAL_UNPAID_STATUSES = frozenset(
    {
        "expired",
        "failed",
    }
)
_CLOCK_SKEW_SECONDS = 5


@dataclass(frozen=True, slots=True)
class BillingRetentionReport:
    deleted_unpaid_attempts: int
    deleted_financial_records: int


def cleanup_expired_billing_records(
    db: Database,
    *,
    now: int | None = None,
) -> BillingRetentionReport:
    """Delete only records whose bounded retention and compliance gates permit it."""
    current_time = int(time.time()) if now is None else now
    if type(current_time) is not int or current_time <= 0:
        raise ValueError("Billing retention cutoff must be a positive integer")
    if current_time > int(time.time()) + _CLOCK_SKEW_SECONDS:
        raise ValueError("Billing retention cutoff cannot be in the future")
    with db.session() as session:
        # The 0014 database trigger independently bounds this transaction-local
        # cutoff to database time. It allows expired contract confirmations to
        # be deleted, while pending withdrawals remain append-only.
        session.execute(
            text("SELECT set_config('gsubs.billing_retention_cutoff', :cutoff, true)"),
            {"cutoff": str(current_time)},
        )
        invoice_exists = (
            select(DbBillingInvoice.id)
            .where(
                DbBillingInvoice.purchase_id == DbCreditPurchase.id,
            )
            .exists()
        )
        reversal_exists = (
            select(DbCreditPurchaseReversal.id)
            .where(
                DbCreditPurchaseReversal.purchase_id == DbCreditPurchase.id,
            )
            .exists()
        )
        confirmation_exists = (
            select(DbBillingContractConfirmation.id)
            .where(
                DbBillingContractConfirmation.purchase_id == DbCreditPurchase.id,
            )
            .exists()
        )
        withdrawal_exists = (
            select(DbBillingWithdrawalRequest.id)
            .where(
                DbBillingWithdrawalRequest.purchase_id == DbCreditPurchase.id,
            )
            .exists()
        )
        payment_snapshot_absent = or_(
            DbCreditPurchase.payment_snapshot.is_(None),
            DbCreditPurchase.payment_snapshot == JSON.NULL,
        )
        unpaid_ids = list(
            session.scalars(
                select(DbCreditPurchase.id)
                .where(
                    DbCreditPurchase.financial_retention_until <= current_time,
                    DbCreditPurchase.fulfilled_at.is_(None),
                    DbCreditPurchase.payment_intent_id.is_(None),
                    payment_snapshot_absent,
                    DbCreditPurchase.status.in_(_TERMINAL_UNPAID_STATUSES),
                    ~invoice_exists,
                    ~reversal_exists,
                    ~confirmation_exists,
                    ~withdrawal_exists,
                )
                .with_for_update(
                    of=DbCreditPurchase,
                    skip_locked=True,
                )
            )
        )
        if unpaid_ids:
            session.execute(delete(DbCreditPurchase).where(DbCreditPurchase.id.in_(unpaid_ids)))

        blocking_reversal_exists = (
            select(DbCreditPurchaseReversal.id)
            .where(
                DbCreditPurchaseReversal.purchase_id == DbCreditPurchase.id,
                DbCreditPurchaseReversal.active.is_(True),
                or_(
                    DbCreditPurchaseReversal.kind == "dispute",
                    and_(
                        DbCreditPurchaseReversal.kind == "refund",
                        DbCreditPurchaseReversal.status.in_(
                            ("pending", "requires_action"),
                        ),
                    ),
                ),
            )
            .exists()
        )
        unexpired_reversal_exists = (
            select(DbCreditPurchaseReversal.id)
            .where(
                DbCreditPurchaseReversal.purchase_id == DbCreditPurchase.id,
                func.public.gsubs_financial_retention_deadline(
                    func.greatest(
                        DbCreditPurchaseReversal.provider_event_created,
                        DbCreditPurchaseReversal.created_at,
                        DbCreditPurchaseReversal.updated_at,
                    )
                )
                > current_time,
            )
            .exists()
        )
        pending_withdrawal_exists = (
            select(DbBillingWithdrawalRequest.id)
            .where(
                DbBillingWithdrawalRequest.purchase_id == DbCreditPurchase.id,
                DbBillingWithdrawalRequest.status == "pending_manual_review",
                ~select(DbBillingWithdrawalResolution.id)
                .where(
                    DbBillingWithdrawalResolution.withdrawal_id == DbBillingWithdrawalRequest.id,
                )
                .exists(),
            )
            .exists()
        )
        unexpired_adjustment_exists = (
            select(DbBillingAdjustmentRecord.id)
            .where(
                DbBillingAdjustmentRecord.purchase_id == DbCreditPurchase.id,
                DbBillingAdjustmentRecord.financial_retention_until > current_time,
            )
            .exists()
        )
        unexpired_resolution_exists = (
            select(DbBillingWithdrawalResolution.id)
            .where(
                DbBillingWithdrawalResolution.purchase_id == DbCreditPurchase.id,
                DbBillingWithdrawalResolution.financial_retention_until > current_time,
            )
            .exists()
        )
        unexpired_confirmation_exists = (
            select(DbBillingContractConfirmation.id)
            .where(
                DbBillingContractConfirmation.purchase_id == DbCreditPurchase.id,
                DbBillingContractConfirmation.financial_retention_until > current_time,
            )
            .exists()
        )
        payment_snapshot_present = and_(
            DbCreditPurchase.payment_snapshot.is_not(None),
            DbCreditPurchase.payment_snapshot != JSON.NULL,
        )
        financial_ids = list(
            session.scalars(
                select(DbCreditPurchase.id)
                .join(
                    DbBillingInvoice,
                    DbBillingInvoice.purchase_id == DbCreditPurchase.id,
                )
                .where(
                    DbCreditPurchase.financial_retention_until <= current_time,
                    DbBillingInvoice.financial_retention_until <= current_time,
                    DbBillingInvoice.document_status == "issued",
                    DbCreditPurchase.dispute_active.is_(False),
                    ~blocking_reversal_exists,
                    ~unexpired_reversal_exists,
                    ~pending_withdrawal_exists,
                    ~unexpired_adjustment_exists,
                    ~unexpired_resolution_exists,
                    ~unexpired_confirmation_exists,
                    or_(
                        DbCreditPurchase.fulfilled_at.is_not(None),
                        DbCreditPurchase.payment_intent_id.is_not(None),
                        payment_snapshot_present,
                    ),
                )
                .with_for_update(
                    of=DbCreditPurchase,
                    skip_locked=True,
                )
            )
        )
        if financial_ids:
            # Resolved requests are the retention root. Their database FK
            # cascades to the matching expired resolution, while the trigger
            # refuses this delete when no completed resolution exists.
            session.execute(
                delete(DbBillingWithdrawalRequest).where(
                    DbBillingWithdrawalRequest.purchase_id.in_(
                        financial_ids,
                    ),
                    DbBillingWithdrawalRequest.financial_retention_until <= current_time,
                )
            )
            session.execute(
                delete(DbBillingAdjustmentRecord).where(
                    DbBillingAdjustmentRecord.purchase_id.in_(
                        financial_ids,
                    ),
                    DbBillingAdjustmentRecord.financial_retention_until <= current_time,
                )
            )
            session.execute(
                delete(DbBillingContractConfirmation).where(
                    DbBillingContractConfirmation.purchase_id.in_(
                        financial_ids,
                    ),
                    DbBillingContractConfirmation.financial_retention_until <= current_time,
                )
            )
            session.execute(
                delete(DbCreditPurchaseReversal).where(
                    DbCreditPurchaseReversal.purchase_id.in_(financial_ids),
                )
            )
            session.execute(
                delete(DbBillingInvoice).where(
                    DbBillingInvoice.purchase_id.in_(financial_ids),
                )
            )
            session.execute(
                delete(DbCreditPurchase).where(
                    DbCreditPurchase.id.in_(financial_ids),
                )
            )

    return BillingRetentionReport(
        deleted_unpaid_attempts=len(unpaid_ids),
        deleted_financial_records=len(financial_ids),
    )
