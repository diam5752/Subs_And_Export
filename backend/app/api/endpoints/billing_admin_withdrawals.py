"""Manual consumer-withdrawal resolution endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.endpoints.billing_admin_models import (
    ResolveWithdrawalRequest,
    WithdrawalResolutionResponse,
)
from backend.app.api.endpoints.billing_admin_support import (
    _disable_sensitive_response_caching,
    _ensure_admin,
    _ensure_recent_admin_session,
    _withdrawal_resolution_response,
)
from backend.app.core.auth import SessionStore, User
from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
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
    new_withdrawal_resolution,
    verify_withdrawal_resolution,
)

from ..deps import (
    get_current_session_token,
    get_current_user,
    get_db,
    get_session_store,
)

router = APIRouter()


@router.post(
    "/admin/withdrawals/{withdrawal_id}/resolve",
    response_model=WithdrawalResolutionResponse,
)
def resolve_withdrawal_review(
    payload: ResolveWithdrawalRequest,
    response: Response,
    withdrawal_id: str = Path(
        ...,
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    current_token: str = Depends(get_current_session_token),
    session_store: SessionStore = Depends(get_session_store),
    db: Database = Depends(get_db),
) -> WithdrawalResolutionResponse:
    """Record a final human decision after all accepted-case actions exist."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    now = int(time.time())
    _ensure_recent_admin_session(
        token=current_token,
        session_store=session_store,
        now=now,
    )
    try:
        with db.session() as session:
            purchase_id = session.scalar(
                select(DbBillingWithdrawalRequest.purchase_id)
                .where(
                    DbBillingWithdrawalRequest.id == withdrawal_id,
                )
                .limit(1)
            )
            if purchase_id is None:
                raise HTTPException(
                    status_code=404,
                    detail="Withdrawal review not found",
                )
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            withdrawal = session.scalar(
                select(DbBillingWithdrawalRequest)
                .where(
                    DbBillingWithdrawalRequest.id == withdrawal_id,
                    DbBillingWithdrawalRequest.purchase_id == purchase_id,
                )
                .with_for_update()
                .limit(1)
            )
            confirmation = session.scalar(
                select(DbBillingContractConfirmation)
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase_id,
                )
                .limit(1)
            )
            if purchase is None or withdrawal is None or confirmation is None:
                raise HTTPException(
                    status_code=404,
                    detail="Withdrawal review not found",
                )
            verify_contract_confirmation(
                confirmation,
                purchase=purchase,
            )
            verify_withdrawal_record(
                withdrawal,
                purchase=purchase,
                confirmation=confirmation,
            )

            adjustment: DbBillingAdjustmentRecord | None = None
            reversal: DbCreditPurchaseReversal | None = None
            if payload.adjustment_id is not None:
                adjustment = session.scalar(
                    select(DbBillingAdjustmentRecord)
                    .where(
                        DbBillingAdjustmentRecord.id == payload.adjustment_id,
                        DbBillingAdjustmentRecord.purchase_id == purchase.id,
                    )
                    .limit(1)
                )
                if adjustment is None:
                    raise HTTPException(
                        status_code=409,
                        detail=("Accepted withdrawal adjustment was not found"),
                    )
                reversal = session.scalar(
                    select(DbCreditPurchaseReversal)
                    .where(
                        DbCreditPurchaseReversal.id == adjustment.reversal_id,
                        DbCreditPurchaseReversal.purchase_id == purchase.id,
                    )
                    .with_for_update()
                    .limit(1)
                )
                if reversal is None:
                    raise HTTPException(
                        status_code=409,
                        detail=("Accepted withdrawal Stripe refund was not found"),
                    )

            existing = session.scalar(
                select(DbBillingWithdrawalResolution)
                .where(
                    DbBillingWithdrawalResolution.withdrawal_id == withdrawal.id,
                )
                .limit(1)
            )
            if existing is not None:
                verify_withdrawal_resolution(
                    existing,
                    withdrawal=withdrawal,
                    purchase=purchase,
                    adjustment=adjustment,
                    reversal=reversal,
                )
                if (
                    existing.decision != payload.decision
                    or existing.adjustment_id != payload.adjustment_id
                    or existing.resolution_snapshot.get(
                        "customer_explanation",
                    )
                    != payload.customer_explanation
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=("Withdrawal review has already been resolved with different evidence"),
                    )
                return _withdrawal_resolution_response(existing)

            resolution = new_withdrawal_resolution(
                withdrawal=withdrawal,
                purchase=purchase,
                decision=payload.decision,
                customer_explanation=payload.customer_explanation,
                actor_user_id=current_user.id,
                resolved_at=now,
                adjustment=adjustment,
                reversal=reversal,
            )
            session.add(resolution)
            session.flush()
            verify_withdrawal_resolution(
                resolution,
                withdrawal=withdrawal,
                purchase=purchase,
                adjustment=adjustment,
                reversal=reversal,
            )
            resolution_response = _withdrawal_resolution_response(
                resolution,
            )
    except BillingConsumerRecordConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=("Withdrawal request evidence failed integrity validation"),
        ) from exc
    except BillingManualRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=("Withdrawal review conflicts with an existing resolution"),
        ) from exc
    return resolution_response
