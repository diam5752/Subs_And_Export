"""Read-only queues for pending billing-admin review."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_, select

from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingInvoicesResponse,
    PendingRefundReview,
    PendingRefundReviewsResponse,
    PendingWithdrawalAdjustment,
    PendingWithdrawalReview,
    PendingWithdrawalReviewsResponse,
)
from backend.app.api.endpoints.billing_admin_support import (
    _PENDING_DOCUMENT_STATUSES,
    _disable_sensitive_response_caching,
    _ensure_admin,
    _pending_invoice,
    _requires_reversal_review_predicate,
    _snapshot_mapping,
    _snapshot_string,
)
from backend.app.core.auth import User
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
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordConflictError,
    verify_contract_confirmation,
    verify_withdrawal_record,
)
from backend.app.services.billing_manual_records import (
    BillingManualRecordError,
    verify_billing_adjustment_record,
)

from ..deps import (
    get_current_user,
    get_db,
)

router = APIRouter()


def _pending_withdrawal_adjustment(
    adjustment: DbBillingAdjustmentRecord,
    reversal: DbCreditPurchaseReversal,
    *,
    purchase: DbCreditPurchase,
) -> PendingWithdrawalAdjustment:
    try:
        verify_billing_adjustment_record(
            adjustment,
            purchase=purchase,
            reversal=reversal,
        )
    except BillingManualRecordError as exc:
        raise HTTPException(
            status_code=409,
            detail="Withdrawal review is unavailable because refund evidence failed integrity validation",
        ) from exc
    return PendingWithdrawalAdjustment(
        adjustment_id=adjustment.id,
        stripe_refund_id=reversal.provider_reversal_id,
        amount_cents=adjustment.amount_cents,
        currency=adjustment.currency,
        aade_document_type=adjustment.aade_document_type,
        aade_series=adjustment.aade_series,
        aade_aa=adjustment.aade_aa,
        aade_mark=adjustment.aade_mark,
        issued_at=adjustment.issued_at,
    )


def _pending_withdrawal_review(
    withdrawal: DbBillingWithdrawalRequest,
    purchase: DbCreditPurchase,
    confirmation: DbBillingContractConfirmation,
    adjustments: list[tuple[DbBillingAdjustmentRecord, DbCreditPurchaseReversal]],
) -> PendingWithdrawalReview:
    try:
        verify_contract_confirmation(confirmation, purchase=purchase)
        verify_withdrawal_record(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
    except BillingConsumerRecordConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="Withdrawal review is unavailable because durable request evidence failed integrity validation",
        ) from exc
    request_snapshot = _snapshot_mapping(withdrawal.request_snapshot)
    electronic_means = _snapshot_mapping(
        request_snapshot.get("confirmation_electronic_means"),
    )
    confirmed_name = _snapshot_string(request_snapshot, "confirmed_name")
    confirmation_email = _snapshot_string(electronic_means, "address")
    if confirmed_name is None or confirmation_email is None:
        raise HTTPException(
            status_code=409,
            detail="Withdrawal request contact evidence is incomplete",
        )
    return PendingWithdrawalReview(
        withdrawal_id=withdrawal.id,
        purchase_id=purchase.id,
        locale=withdrawal.locale,
        submitted_at=withdrawal.submitted_at,
        contract_concluded_at=confirmation.contract_concluded_at,
        confirmed_name=confirmed_name,
        confirmation_email=confirmation_email,
        available_adjustments=[
            _pending_withdrawal_adjustment(
                adjustment,
                reversal,
                purchase=purchase,
            )
            for adjustment, reversal in adjustments
        ],
    )


@router.get(
    "/admin/invoices/pending",
    response_model=PendingBillingInvoicesResponse,
)
def list_pending_billing_invoices(
    response: Response,
    limit: int = Query(100, ge=1, le=100),
    after: str | None = Query(
        None,
        min_length=34,
        max_length=53,
        pattern=r"^[0-9]{1,20}:[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> PendingBillingInvoicesResponse:
    """List pending documents and issued documents needing reversal review."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    cursor_created_at: int | None = None
    cursor_invoice_id: str | None = None
    if after is not None:
        raw_created_at, cursor_invoice_id = after.split(":", maxsplit=1)
        cursor_created_at = int(raw_created_at)

    with db.session() as session:
        query = (
            select(DbBillingInvoice, DbCreditPurchase)
            .join(
                DbCreditPurchase,
                DbCreditPurchase.id == DbBillingInvoice.purchase_id,
            )
            .where(
                or_(
                    DbBillingInvoice.document_status.in_(_PENDING_DOCUMENT_STATUSES),
                    _requires_reversal_review_predicate(),
                )
            )
        )
        if cursor_created_at is not None and cursor_invoice_id is not None:
            query = query.where(
                or_(
                    DbBillingInvoice.created_at > cursor_created_at,
                    and_(
                        DbBillingInvoice.created_at == cursor_created_at,
                        DbBillingInvoice.id > cursor_invoice_id,
                    ),
                )
            )
        rows = session.execute(
            query.order_by(
                DbBillingInvoice.created_at.asc(),
                DbBillingInvoice.id.asc(),
            ).limit(limit + 1)
        ).all()
        page = rows[:limit]
        items = [_pending_invoice(invoice=invoice, purchase=purchase) for invoice, purchase in page]
        next_cursor = None
        if len(rows) > limit and page:
            last_invoice = page[-1][0]
            next_cursor = f"{last_invoice.created_at}:{last_invoice.id}"
    return PendingBillingInvoicesResponse(
        items=items,
        count=len(items),
        next_cursor=next_cursor,
    )


@router.get(
    "/admin/refunds/pending",
    response_model=PendingRefundReviewsResponse,
)
def list_pending_refund_reviews(
    response: Response,
    limit: int = Query(100, ge=1, le=100),
    after: str | None = Query(
        None,
        min_length=34,
        max_length=53,
        pattern=r"^[0-9]{1,20}:[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> PendingRefundReviewsResponse:
    """List completed Stripe refunds missing a recorded AADE adjustment."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    cursor_created_at: int | None = None
    cursor_reversal_id: str | None = None
    if after is not None:
        raw_created_at, cursor_reversal_id = after.split(":", maxsplit=1)
        cursor_created_at = int(raw_created_at)

    with db.session() as session:
        query = (
            select(
                DbCreditPurchaseReversal,
                DbCreditPurchase,
                DbBillingInvoice,
            )
            .join(
                DbCreditPurchase,
                DbCreditPurchase.id == DbCreditPurchaseReversal.purchase_id,
            )
            .join(
                DbBillingInvoice,
                DbBillingInvoice.purchase_id == DbCreditPurchase.id,
            )
            .outerjoin(
                DbBillingAdjustmentRecord,
                DbBillingAdjustmentRecord.reversal_id == DbCreditPurchaseReversal.id,
            )
            .where(
                DbCreditPurchaseReversal.provider == "stripe",
                DbCreditPurchaseReversal.kind == "refund",
                DbCreditPurchaseReversal.provider_reversal_id.like(
                    "re_%",
                ),
                DbCreditPurchaseReversal.status == "succeeded",
                DbCreditPurchaseReversal.active.is_(True),
                DbBillingAdjustmentRecord.id.is_(None),
            )
        )
        if cursor_created_at is not None and cursor_reversal_id is not None:
            query = query.where(
                or_(
                    DbCreditPurchaseReversal.provider_event_created > cursor_created_at,
                    and_(
                        DbCreditPurchaseReversal.provider_event_created == cursor_created_at,
                        DbCreditPurchaseReversal.id > cursor_reversal_id,
                    ),
                )
            )
        rows = session.execute(
            query.order_by(
                DbCreditPurchaseReversal.provider_event_created.asc(),
                DbCreditPurchaseReversal.id.asc(),
            ).limit(limit + 1)
        ).all()
        page = rows[:limit]
        purchase_ids = [purchase.id for _, purchase, _ in page]
        linked_withdrawals = (
            {
                withdrawal.purchase_id: withdrawal.id
                for withdrawal in session.scalars(
                    select(DbBillingWithdrawalRequest)
                    .outerjoin(
                        DbBillingWithdrawalResolution,
                        DbBillingWithdrawalResolution.withdrawal_id == DbBillingWithdrawalRequest.id,
                    )
                    .where(
                        DbBillingWithdrawalRequest.purchase_id.in_(
                            purchase_ids,
                        ),
                        DbBillingWithdrawalResolution.id.is_(None),
                    )
                )
            }
            if purchase_ids
            else {}
        )
        items = [
            PendingRefundReview(
                reversal_id=reversal.id,
                stripe_refund_id=reversal.provider_reversal_id,
                stripe_refund_status=reversal.status,
                stripe_refund_created_at=(reversal.provider_event_created),
                amount_cents=reversal.amount_cents,
                currency=reversal.currency,
                linked_withdrawal_id=linked_withdrawals.get(
                    purchase.id,
                ),
                original_invoice=_pending_invoice(
                    invoice=invoice,
                    purchase=purchase,
                ),
            )
            for reversal, purchase, invoice in page
        ]
        next_cursor = None
        if len(rows) > limit and page:
            last_reversal = page[-1][0]
            next_cursor = f"{last_reversal.provider_event_created}:{last_reversal.id}"
    return PendingRefundReviewsResponse(
        items=items,
        count=len(items),
        next_cursor=next_cursor,
    )


@router.get(
    "/admin/withdrawals/pending",
    response_model=PendingWithdrawalReviewsResponse,
)
def list_pending_withdrawal_reviews(
    response: Response,
    limit: int = Query(100, ge=1, le=100),
    after: str | None = Query(
        None,
        min_length=34,
        max_length=53,
        pattern=r"^[0-9]{1,20}:[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> PendingWithdrawalReviewsResponse:
    """List unresolved consumer requests and completed manual evidence."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    cursor_submitted_at: int | None = None
    cursor_withdrawal_id: str | None = None
    if after is not None:
        raw_submitted_at, cursor_withdrawal_id = after.split(
            ":",
            maxsplit=1,
        )
        cursor_submitted_at = int(raw_submitted_at)

    with db.session() as session:
        query = (
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
            .outerjoin(
                DbBillingWithdrawalResolution,
                DbBillingWithdrawalResolution.withdrawal_id == DbBillingWithdrawalRequest.id,
            )
            .where(DbBillingWithdrawalResolution.id.is_(None))
        )
        if cursor_submitted_at is not None and cursor_withdrawal_id is not None:
            query = query.where(
                or_(
                    DbBillingWithdrawalRequest.submitted_at > cursor_submitted_at,
                    and_(
                        DbBillingWithdrawalRequest.submitted_at == cursor_submitted_at,
                        DbBillingWithdrawalRequest.id > cursor_withdrawal_id,
                    ),
                )
            )
        rows = session.execute(
            query.order_by(
                DbBillingWithdrawalRequest.submitted_at.asc(),
                DbBillingWithdrawalRequest.id.asc(),
            ).limit(limit + 1)
        ).all()
        page = rows[:limit]
        purchase_ids = [purchase.id for _, purchase, _ in page]
        adjustment_rows = (
            session.execute(
                select(
                    DbBillingAdjustmentRecord,
                    DbCreditPurchaseReversal,
                )
                .join(
                    DbCreditPurchaseReversal,
                    DbCreditPurchaseReversal.id == DbBillingAdjustmentRecord.reversal_id,
                )
                .outerjoin(
                    DbBillingWithdrawalResolution,
                    DbBillingWithdrawalResolution.adjustment_id == DbBillingAdjustmentRecord.id,
                )
                .where(
                    DbBillingAdjustmentRecord.purchase_id.in_(purchase_ids),
                    DbBillingWithdrawalResolution.id.is_(None),
                    DbCreditPurchaseReversal.status == "succeeded",
                    DbCreditPurchaseReversal.active.is_(True),
                )
            ).all()
            if purchase_ids
            else []
        )
        adjustments_by_purchase: dict[
            str,
            list[
                tuple[
                    DbBillingAdjustmentRecord,
                    DbCreditPurchaseReversal,
                ]
            ],
        ] = {}
        for adjustment, reversal in adjustment_rows:
            adjustments_by_purchase.setdefault(
                adjustment.purchase_id,
                [],
            ).append((adjustment, reversal))

        items = [
            _pending_withdrawal_review(
                withdrawal,
                purchase,
                confirmation,
                adjustments_by_purchase.get(purchase.id, []),
            )
            for withdrawal, purchase, confirmation in page
        ]
        next_cursor = None
        if len(rows) > limit and page:
            last_withdrawal = page[-1][0]
            next_cursor = f"{last_withdrawal.submitted_at}:{last_withdrawal.id}"
    return PendingWithdrawalReviewsResponse(
        items=items,
        count=len(items),
        next_cursor=next_cursor,
    )
