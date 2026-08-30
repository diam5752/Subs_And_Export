"""Deterministic GDPR account export assembly."""

import time
from typing import Any

from sqlalchemy import select

from ..core.auth import User
from ..core.database import Database
from ..db.models import (
    DbCreditPromotionClaim,
    DbOAuthState,
    DbPointTransaction,
    DbProductFeedback,
    DbProviderBudgetReservation,
    DbSession,
    DbTokenUsage,
    DbUsageLedger,
    DbUserPoints,
)
from .account_data_export_billing import build_billing_purchases
from .history import HistoryStore
from .jobs import JobStore


def build_account_data_export(
    *,
    current_user: User,
    job_store: JobStore,
    history_store: HistoryStore,
    db: Database,
) -> Any:
    """Export all personal data (GDPR Right to Access)."""
    profile = {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "created_at": current_user.created_at,
        "provider": current_user.provider,
        "avatar_url": current_user.avatar_url,
        "email_verified": current_user.email_verified,
    }

    # Export and erasure must never inherit the interactive UI's bounded list.
    jobs = job_store.list_all_jobs_for_user(current_user.id)
    job_ids = [job.id for job in jobs]
    history = history_store.all_for_user(current_user)
    now = int(time.time())

    with db.session() as session:
        wallet_row = session.get(DbUserPoints, current_user.id)
        wallet = (
            {
                "balance": wallet_row.balance,
                "paid_balance": wallet_row.paid_balance,
                "promotional_balance": wallet_row.balance - wallet_row.paid_balance,
                "reversal_debt": wallet_row.reversal_debt,
                "updated_at": wallet_row.updated_at,
            }
            if wallet_row is not None
            else None
        )
        point_transaction_rows = session.scalars(
            select(DbPointTransaction)
            .where(DbPointTransaction.user_id == current_user.id)
            .order_by(
                DbPointTransaction.created_at.asc(),
                DbPointTransaction.id.asc(),
            )
        ).all()
        point_transactions = [
            {
                "id": row.id,
                "delta": row.delta,
                "paid_delta": row.paid_delta,
                "reversal_debt_delta": row.reversal_debt_delta,
                "reason": row.reason,
                "meta": row.meta,
                "created_at": row.created_at,
            }
            for row in point_transaction_rows
        ]
        credit_promotion_claim_rows = session.scalars(
            select(DbCreditPromotionClaim)
            .where(DbCreditPromotionClaim.user_id == current_user.id)
            .order_by(
                DbCreditPromotionClaim.claimed_at.asc(),
                DbCreditPromotionClaim.campaign_id.asc(),
            )
        ).all()
        credit_promotion_claims = [
            {
                "campaign_id": row.campaign_id,
                "slot_number": row.slot_number,
                "credit_amount": row.credit_amount,
                "point_transaction_id": row.point_transaction_id,
                "claimed_at": row.claimed_at,
            }
            for row in credit_promotion_claim_rows
        ]

        usage_rows = session.scalars(
            select(DbUsageLedger)
            .where(DbUsageLedger.user_id == current_user.id)
            .order_by(
                DbUsageLedger.created_at.asc(),
                DbUsageLedger.id.asc(),
            )
        ).all()
        usage_ledger = [
            {
                "id": row.id,
                "job_id": row.job_id,
                "action": row.action,
                "provider": row.provider,
                "endpoint": row.endpoint,
                "model": row.model,
                "tier": row.tier,
                "units": row.units,
                "cost_usd": row.cost_usd,
                "credits_reserved": row.credits_reserved,
                "paid_credits_reserved": row.paid_credits_reserved,
                "credits_charged": row.credits_charged,
                "min_credits": row.min_credits,
                "currency": row.currency,
                "status": row.status,
                "error": row.error,
                "idempotency_key": row.idempotency_key,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in usage_rows
        ]

        token_usage_rows = (
            session.scalars(
                select(DbTokenUsage)
                .where(DbTokenUsage.job_id.in_(job_ids))
                .order_by(
                    DbTokenUsage.timestamp.asc(),
                    DbTokenUsage.id.asc(),
                )
            ).all()
            if job_ids
            else []
        )
        token_usage = [
            {
                "id": row.id,
                "job_id": row.job_id,
                "model_id": row.model_id,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "total_tokens": row.total_tokens,
                "cost": row.cost,
                "timestamp": row.timestamp,
            }
            for row in token_usage_rows
        ]

        usage_idempotency_keys = [row.idempotency_key for row in usage_rows if row.idempotency_key is not None]
        provider_reservation_rows = (
            session.scalars(
                select(DbProviderBudgetReservation)
                .where(DbProviderBudgetReservation.idempotency_key.in_(usage_idempotency_keys))
                .order_by(
                    DbProviderBudgetReservation.created_at.asc(),
                    DbProviderBudgetReservation.idempotency_key.asc(),
                )
            ).all()
            if usage_idempotency_keys
            else []
        )
        provider_budget_reservations = [
            {
                "idempotency_key": row.idempotency_key,
                "daily_window_key": row.daily_window_key,
                "monthly_window_key": row.monthly_window_key,
                "estimated_usd": row.estimated_usd,
                "actual_usd": row.actual_usd,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in provider_reservation_rows
        ]

        session_rows = session.scalars(
            select(DbSession)
            .where(DbSession.user_id == current_user.id)
            .order_by(
                DbSession.created_at.asc(),
                DbSession.expires_at.asc(),
            )
        ).all()
        sessions = [
            {
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "user_agent": row.user_agent,
                "active": row.expires_at > now,
            }
            for row in session_rows
        ]

        oauth_rows = session.scalars(
            select(DbOAuthState)
            .where(DbOAuthState.user_id == current_user.id)
            .order_by(
                DbOAuthState.created_at.asc(),
                DbOAuthState.provider.asc(),
            )
        ).all()
        oauth_states = [
            {
                "provider": row.provider,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "user_agent": row.user_agent,
                "ip": row.ip,
                "active": row.expires_at > now,
            }
            for row in oauth_rows
        ]

        feedback_rows = session.scalars(
            select(DbProductFeedback)
            .where(DbProductFeedback.submitter_user_id == current_user.id)
            .order_by(
                DbProductFeedback.created_at.asc(),
                DbProductFeedback.id.asc(),
            )
        ).all()
        product_feedback = [
            {
                "id": row.id,
                "category": row.category,
                "status": row.status,
                "message": row.message,
                "source_path": row.source_path,
                "page_title": row.page_title,
                "submitter_key_hash": row.submitter_key_hash,
                "message_hash": row.message_hash,
                "created_at": row.created_at,
                "notification_status": row.notification_status,
                "notification_attempts": row.notification_attempts,
                "notification_sent_at": row.notification_sent_at,
            }
            for row in feedback_rows
        ]
        billing_purchases = build_billing_purchases(session, current_user.id)

    return {
        "profile": profile,
        "jobs": jobs,
        "history": history,
        "wallet": wallet,
        "point_transactions": point_transactions,
        "credit_promotion_claims": credit_promotion_claims,
        "usage_ledger": usage_ledger,
        "token_usage": token_usage,
        "provider_budget_reservations": provider_budget_reservations,
        "sessions": sessions,
        "oauth_states": oauth_states,
        "product_feedback": product_feedback,
        "billing_purchases": billing_purchases,
    }
