import logging
import re
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...core.auth import (
    GoogleAuthError,
    SessionStore,
    User,
    UserStore,
    create_google_auth_nonce,
    google_auth_nonce_hash,
    google_client_id,
    verify_google_id_token,
)
from ...core.config import settings
from ...core.database import Database
from ...core.erasure_journal import ErasureJournalError, configured_erasure_journal
from ...core.errors import sanitize_error
from ...core.ratelimit import limiter_auth_change, limiter_login, limiter_register, limiter_signup_daily
from ...core.workspace_deletion import JobWorkspaceLockTimeoutError
from ...db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPromotionClaim,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbOAuthState,
    DbPointTransaction,
    DbProductFeedback,
    DbProviderBudgetReservation,
    DbSession,
    DbTokenUsage,
    DbUsageLedger,
    DbUserPoints,
)
from ...services.account_erasure import ActiveAccountJobsError, erase_account_and_media
from ...services.billing import BillingConflictError, BillingService
from ...services.billing_consumer_records import (
    BillingConsumerRecordConflictError,
    verify_contract_confirmation,
    verify_withdrawal_record,
)
from ...services.billing_manual_records import (
    BillingManualRecordError,
    verify_billing_adjustment_record,
    verify_withdrawal_resolution,
)
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.login_promotion import LoginPromotionStore
from ...services.points import PointsStore
from ..deps import (
    get_billing_service,
    get_current_session_token,
    get_current_user,
    get_db,
    get_history_store,
    get_job_store,
    get_login_promotion_store,
    get_points_store,
    get_session_store,
    get_user_store,
)

router = APIRouter()
media_router = APIRouter()
logger = logging.getLogger(__name__)

ACCOUNT_DELETION_NOTICE = (
    "Account and media are permanently deleted; legally required financial records are retained in detached form."
)
MEDIA_SESSION_COOKIE_NAME = "gsubs_media_session"
_MEDIA_SESSION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def media_session_cookie_settings() -> dict[str, Any]:
    """Return the narrow cookie policy used only for authenticated media GETs."""
    return {
        "key": MEDIA_SESSION_COOKIE_NAME,
        "httponly": True,
        "secure": not settings.is_dev,
        "samesite": "lax",
        "path": "/static",
        "max_age": SessionStore.SESSION_TTL_SECONDS,
    }


def _validated_media_session_token(token: str) -> str:
    """Return only the canonical URL-safe 256-bit session-token encoding."""
    if _MEDIA_SESSION_TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("Invalid media session token")
    return token


def _set_media_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        value=_validated_media_session_token(token),
        **media_session_cookie_settings(),
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_media_session_cookie(response: Response) -> None:
    cookie_settings = media_session_cookie_settings()
    cookie_settings.pop("max_age")
    response.delete_cookie(**cookie_settings)
    response.headers["Cache-Control"] = "no-store"


class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
    name: str = Field(..., max_length=100)


class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    name: str
    beta_credits_awarded: int = Field(default=0, ge=0)


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    provider: str
    avatar_url: str | None = None


class LogoutResponse(BaseModel):
    status: Literal["success"] = "success"


def _claim_beta_login_credits(
    *,
    user: User,
    promotion_store: LoginPromotionStore,
) -> int:
    """Fail closed so an eligible login is never silently denied its grant."""
    try:
        result = promotion_store.claim_for_login(
            user.id,
            enabled=settings.beta_login_promotion_enabled,
        )
    except Exception as exc:
        logger.error(
            "Beta login credit claim failed: %s",
            sanitize_error(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is temporarily unavailable. Please try again.",
        ) from exc
    return result.awarded_credits


def _assert_trusted_media_logout_request(request: Request) -> None:
    """Reject browser cross-site attempts to spend a private-media cookie."""
    if request.headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site logout is not allowed")

    origin = request.headers.get("origin")
    if origin is None:
        # Non-browser clients do not consistently send Origin. Browsers send
        # Origin or Sec-Fetch-Site for credentialed POSTs, while SameSite=Lax
        # provides the independent cross-site cookie boundary.
        return

    request_origin = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    allowed_origins = {request_origin, *(value.rstrip("/") for value in settings.allowed_origins)}
    if settings.is_dev:
        allowed_origins.update(
            {
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8080",
                "http://127.0.0.1:8080",
            }
        )
    if origin.rstrip("/") not in allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted logout origin")


@media_router.post("/static/auth/logout", response_model=LogoutResponse)
def logout_media_cookie_session(
    request: Request,
    response: Response,
    session_store: SessionStore = Depends(get_session_store),
) -> LogoutResponse:
    """Idempotently revoke the exact session carried by the media cookie."""
    _assert_trusted_media_logout_request(request)
    token = request.cookies.get(MEDIA_SESSION_COOKIE_NAME)
    if token:
        session_store.revoke(token)
    _clear_media_session_cookie(response)
    return LogoutResponse()


@router.post(
    "/register", response_model=UserResponse, dependencies=[Depends(limiter_register), Depends(limiter_signup_daily)]
)
def register(user_in: UserCreate, user_store: UserStore = Depends(get_user_store)) -> Any:
    """Register a new user."""
    try:
        user = user_store.register_local_user(email=user_in.email, password=user_in.password, name=user_in.name)
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/token", response_model=Token, dependencies=[Depends(limiter_login)])
def login_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
    promotion_store: LoginPromotionStore = Depends(get_login_promotion_store),
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""
    # Security: Validate input lengths to prevent DoS via massive strings
    if len(form_data.username) > 255:
        raise HTTPException(status_code=400, detail="Email too long")
    if len(form_data.password) > 128:
        raise HTTPException(status_code=400, detail="Password too long")

    user = user_store.authenticate_local(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    beta_credits_awarded = _claim_beta_login_credits(
        user=user,
        promotion_store=promotion_store,
    )
    token = session_store.issue_session(user)
    _set_media_session_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name,
        "beta_credits_awarded": beta_credits_awarded,
    }


@router.get("/me", response_model=UserResponse)
def read_users_me(
    response: Response,
    current_user: User = Depends(get_current_user),
    current_token: str = Depends(get_current_session_token),
) -> Any:
    """Get the current profile and refresh private-media cookie compatibility."""
    _set_media_session_cookie(response, current_token)
    return current_user


@router.post(
    "/logout",
    response_model=LogoutResponse,
    dependencies=[Depends(get_current_user)],
)
def logout_current_session(
    response: Response,
    current_token: str = Depends(get_current_session_token),
    session_store: SessionStore = Depends(get_session_store),
) -> LogoutResponse:
    """Revoke only the bearer session presented by the current client."""
    session_store.revoke(current_token)
    _clear_media_session_cookie(response)
    return LogoutResponse()


class PointsBalanceResponse(BaseModel):
    balance: int
    paid_balance: int
    promotional_balance: int
    reversal_debt: int
    ai_spendable_balance: int


@router.get("/points", response_model=PointsBalanceResponse)
def read_my_points(
    current_user: User = Depends(get_current_user),
    points_store: PointsStore = Depends(get_points_store),
) -> Any:
    """Get current user's points balance."""
    wallet = points_store.get_balances(current_user.id)
    return {
        "balance": wallet.balance,
        "paid_balance": wallet.paid_balance,
        "promotional_balance": wallet.promotional_balance,
        "reversal_debt": wallet.reversal_debt,
        "ai_spendable_balance": wallet.ai_spendable_balance,
    }


class UserUpdateName(BaseModel):
    name: str = Field(..., max_length=100)


@router.put("/me", response_model=UserResponse, dependencies=[Depends(limiter_auth_change)])
def update_user_me(
    user_in: UserUpdateName,
    current_user: User = Depends(get_current_user),
    user_store: UserStore = Depends(get_user_store),
) -> Any:
    """Update current user profile name."""
    user_store.update_name(current_user.id, user_in.name)
    current_user.name = user_in.name
    return current_user


class UserUpdatePassword(BaseModel):
    password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., max_length=128)


@router.put("/password", response_model=Any, dependencies=[Depends(limiter_auth_change)])
def update_password(
    user_in: UserUpdatePassword,
    response: Response,
    current_user: User = Depends(get_current_user),
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
) -> Any:
    """
    Update current user password (local users only).
    Security: Revokes all active sessions upon password change to prevent access by stale tokens.
    """
    if current_user.provider != "local":
        raise HTTPException(status_code=400, detail="Cannot update password for external provider")

    if user_in.password != user_in.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    user_store.update_password(current_user.id, user_in.password)

    # Critical Security Fix: Revoke all existing sessions so that attackers (or old devices)
    # cannot use the old session after password change.
    session_store.revoke_all_sessions(current_user.id)
    _clear_media_session_cookie(response)

    return {"status": "success"}


@router.get("/export", response_model=Any)
def export_my_data(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    db: Database = Depends(get_db),
) -> Any:
    """Export all personal data (GDPR Right to Access)."""
    # Profile
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
                "promotional_balance": (wallet_row.balance - wallet_row.paid_balance),
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

        # Durable financial records belonging to the active account.
        billing_rows = session.execute(
            select(DbCreditPurchase, DbBillingInvoice)
            .outerjoin(
                DbBillingInvoice,
                DbBillingInvoice.purchase_id == DbCreditPurchase.id,
            )
            .where(DbCreditPurchase.user_id == current_user.id)
            .order_by(
                DbCreditPurchase.created_at.asc(),
                DbCreditPurchase.id.asc(),
            )
        ).all()

        reversal_rows_by_purchase: dict[str, list[dict[str, Any]]] = {}
        confirmation_rows_by_purchase: dict[
            str,
            DbBillingContractConfirmation,
        ] = {}
        withdrawal_rows_by_purchase: dict[
            str,
            DbBillingWithdrawalRequest,
        ] = {}
        adjustment_rows_by_purchase: dict[
            str,
            list[DbBillingAdjustmentRecord],
        ] = {}
        resolution_rows_by_purchase: dict[
            str,
            DbBillingWithdrawalResolution,
        ] = {}
        reversal_models_by_id: dict[str, DbCreditPurchaseReversal] = {}
        purchase_ids = [purchase.id for purchase, _invoice in billing_rows]
        if purchase_ids:
            reversal_rows = session.scalars(
                select(DbCreditPurchaseReversal)
                .where(DbCreditPurchaseReversal.purchase_id.in_(purchase_ids))
                .order_by(
                    DbCreditPurchaseReversal.provider_event_created.asc(),
                    DbCreditPurchaseReversal.created_at.asc(),
                    DbCreditPurchaseReversal.id.asc(),
                )
            ).all()
            reversal_models_by_id = {reversal.id: reversal for reversal in reversal_rows}
            for reversal in reversal_rows:
                reversal_rows_by_purchase.setdefault(
                    reversal.purchase_id,
                    [],
                ).append(
                    {
                        "id": reversal.id,
                        "purchase_id": reversal.purchase_id,
                        "provider": reversal.provider,
                        "provider_reversal_id": (reversal.provider_reversal_id),
                        "provider_event_id": reversal.provider_event_id,
                        "provider_event_created": (reversal.provider_event_created),
                        "kind": reversal.kind,
                        "amount_cents": reversal.amount_cents,
                        "currency": reversal.currency,
                        "status": reversal.status,
                        "active": reversal.active,
                        "created_at": reversal.created_at,
                        "updated_at": reversal.updated_at,
                    }
                )
            confirmation_rows = session.scalars(
                select(DbBillingContractConfirmation)
                .where(
                    DbBillingContractConfirmation.purchase_id.in_(
                        purchase_ids,
                    )
                )
                .order_by(
                    DbBillingContractConfirmation.created_at.asc(),
                    DbBillingContractConfirmation.id.asc(),
                )
            ).all()
            confirmation_rows_by_purchase = {
                confirmation.purchase_id: confirmation for confirmation in confirmation_rows
            }
            withdrawal_rows = session.scalars(
                select(DbBillingWithdrawalRequest)
                .where(
                    DbBillingWithdrawalRequest.purchase_id.in_(
                        purchase_ids,
                    )
                )
                .order_by(
                    DbBillingWithdrawalRequest.submitted_at.asc(),
                    DbBillingWithdrawalRequest.id.asc(),
                )
            ).all()
            withdrawal_rows_by_purchase = {withdrawal.purchase_id: withdrawal for withdrawal in withdrawal_rows}
            adjustment_rows = session.scalars(
                select(DbBillingAdjustmentRecord)
                .where(
                    DbBillingAdjustmentRecord.purchase_id.in_(
                        purchase_ids,
                    )
                )
                .order_by(
                    DbBillingAdjustmentRecord.recorded_at.asc(),
                    DbBillingAdjustmentRecord.id.asc(),
                )
            ).all()
            for adjustment in adjustment_rows:
                adjustment_rows_by_purchase.setdefault(
                    adjustment.purchase_id,
                    [],
                ).append(adjustment)
            resolution_rows = session.scalars(
                select(DbBillingWithdrawalResolution)
                .where(
                    DbBillingWithdrawalResolution.purchase_id.in_(
                        purchase_ids,
                    )
                )
                .order_by(
                    DbBillingWithdrawalResolution.resolved_at.asc(),
                    DbBillingWithdrawalResolution.id.asc(),
                )
            ).all()
            resolution_rows_by_purchase = {resolution.purchase_id: resolution for resolution in resolution_rows}

        try:
            for purchase, _invoice in billing_rows:
                confirmation = confirmation_rows_by_purchase.get(
                    purchase.id,
                )
                withdrawal = withdrawal_rows_by_purchase.get(
                    purchase.id,
                )
                adjustments = adjustment_rows_by_purchase.get(
                    purchase.id,
                    [],
                )
                resolution = resolution_rows_by_purchase.get(
                    purchase.id,
                )
                if confirmation is not None:
                    verify_contract_confirmation(
                        confirmation,
                        purchase=purchase,
                    )
                if withdrawal is not None:
                    if confirmation is None:
                        raise BillingConsumerRecordConflictError(
                            "Withdrawal contract confirmation is unavailable",
                        )
                    verify_withdrawal_record(
                        withdrawal,
                        purchase=purchase,
                        confirmation=confirmation,
                    )
                for adjustment_record in adjustments:
                    adjustment_reversal = reversal_models_by_id.get(
                        adjustment_record.reversal_id,
                    )
                    if adjustment_reversal is None:
                        raise BillingManualRecordError(
                            "AADE adjustment Stripe evidence is unavailable",
                        )
                    verify_billing_adjustment_record(
                        adjustment_record,
                        purchase=purchase,
                        reversal=adjustment_reversal,
                    )
                if resolution is not None:
                    if withdrawal is None:
                        raise BillingManualRecordError(
                            "Withdrawal resolution request is unavailable",
                        )
                    resolution_adjustment = (
                        next(
                            (item for item in adjustments if item.id == resolution.adjustment_id),
                            None,
                        )
                        if resolution.adjustment_id is not None
                        else None
                    )
                    resolution_reversal = (
                        reversal_models_by_id.get(
                            resolution_adjustment.reversal_id,
                        )
                        if resolution_adjustment is not None
                        else None
                    )
                    verify_withdrawal_resolution(
                        resolution,
                        withdrawal=withdrawal,
                        purchase=purchase,
                        adjustment=resolution_adjustment,
                        reversal=resolution_reversal,
                    )
        except (
            BillingConsumerRecordConflictError,
            BillingManualRecordError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Billing export is unavailable because durable billing record integrity validation failed."),
            ) from exc

        billing_purchases = [
            {
                "id": purchase.id,
                "provider": purchase.provider,
                "status": purchase.status,
                "created_at": purchase.created_at,
                "fulfilled_at": purchase.fulfilled_at,
                "refunded_amount_cents": purchase.refunded_amount_cents,
                "dispute_active": purchase.dispute_active,
                "reversed_amount_cents": purchase.reversed_amount_cents,
                "reversed_credits": purchase.reversed_credits,
                "reversal_debt_credits": (purchase.reversal_debt_credits),
                "financial_retention_until": (purchase.financial_retention_until),
                "package_snapshot": purchase.snapshot,
                "payment_snapshot": purchase.payment_snapshot,
                "customer_snapshot": purchase.customer_snapshot,
                "tax_snapshot": purchase.tax_snapshot,
                "reversals": reversal_rows_by_purchase.get(
                    purchase.id,
                    [],
                ),
                "aade_adjustment_records": [
                    {
                        "id": adjustment.id,
                        "reversal_id": adjustment.reversal_id,
                        "schema_version": adjustment.schema_version,
                        "provider": adjustment.provider,
                        "document_kind": adjustment.document_kind,
                        "aade_document_type": (adjustment.aade_document_type),
                        "aade_series": adjustment.aade_series,
                        "aade_aa": adjustment.aade_aa,
                        "aade_mark": adjustment.aade_mark,
                        "issued_at": adjustment.issued_at,
                        "amount_cents": adjustment.amount_cents,
                        "currency": adjustment.currency,
                        "recorded_at": adjustment.recorded_at,
                        "document_snapshot": (adjustment.document_snapshot),
                        "financial_retention_until": (adjustment.financial_retention_until),
                    }
                    for adjustment in adjustment_rows_by_purchase.get(
                        purchase.id,
                        [],
                    )
                ],
                "contract_confirmation": (
                    {
                        "id": confirmation.id,
                        "schema_version": confirmation.schema_version,
                        "locale": confirmation.locale,
                        "contract_concluded_at": (confirmation.contract_concluded_at),
                        "mime_type": confirmation.mime_type,
                        "filename": confirmation.filename,
                        "content": confirmation.content_bytes.decode("utf-8"),
                        "content_sha256": confirmation.content_sha256,
                        "consumer_contract_sha256": (confirmation.consumer_contract_sha256),
                        "delivery_channel": confirmation.delivery_channel,
                        "delivery_status": confirmation.delivery_status,
                        "available_at": confirmation.available_at,
                        "financial_retention_until": (confirmation.financial_retention_until),
                    }
                    if (
                        confirmation := confirmation_rows_by_purchase.get(
                            purchase.id,
                        )
                    )
                    is not None
                    else None
                ),
                "withdrawal_request": (
                    {
                        "id": withdrawal.id,
                        "schema_version": withdrawal.schema_version,
                        "locale": withdrawal.locale,
                        "status": withdrawal.status,
                        "request_snapshot": withdrawal.request_snapshot,
                        "request_sha256": withdrawal.request_sha256,
                        "submitted_at": withdrawal.submitted_at,
                        "acknowledgement_mime_type": (withdrawal.acknowledgement_mime_type),
                        "acknowledgement_filename": (withdrawal.acknowledgement_filename),
                        "acknowledgement": (withdrawal.acknowledgement_bytes.decode("utf-8")),
                        "acknowledgement_sha256": (withdrawal.acknowledgement_sha256),
                        "available_at": withdrawal.available_at,
                        "financial_retention_until": (withdrawal.financial_retention_until),
                    }
                    if (
                        withdrawal := withdrawal_rows_by_purchase.get(
                            purchase.id,
                        )
                    )
                    is not None
                    else None
                ),
                "withdrawal_resolution": (
                    {
                        "id": resolution.id,
                        "withdrawal_id": resolution.withdrawal_id,
                        "schema_version": resolution.schema_version,
                        "locale": resolution.locale,
                        "decision": resolution.decision,
                        "reason_code": resolution.reason_code,
                        "adjustment_id": resolution.adjustment_id,
                        "resolution": (resolution.resolution_bytes.decode("utf-8")),
                        "resolution_sha256": (resolution.resolution_sha256),
                        "resolved_at": resolution.resolved_at,
                        "available_at": resolution.available_at,
                        "financial_retention_until": (resolution.financial_retention_until),
                    }
                    if (
                        resolution := resolution_rows_by_purchase.get(
                            purchase.id,
                        )
                    )
                    is not None
                    else None
                ),
                "invoice": (
                    {
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
                        "financial_retention_until": (invoice.financial_retention_until),
                    }
                    if invoice is not None
                    else None
                ),
            }
            for purchase, invoice in billing_rows
        ]

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


@router.delete("/me", response_model=Any, dependencies=[Depends(limiter_auth_change)])
def delete_account(
    response: Response,
    current_user: User = Depends(get_current_user),
    user_store: UserStore = Depends(get_user_store),
    billing_service: BillingService = Depends(get_billing_service),
    db: Database = Depends(get_db),
) -> Any:
    """Account and media are permanently deleted; legally required financial records are retained in detached form."""
    try:
        erase_account_and_media(
            db=db,
            billing_service=billing_service,
            user_store=user_store,
            user_id=current_user.id,
            data_dir=settings.data_dir,
            journal=configured_erasure_journal(),
        )

        _clear_media_session_cookie(response)
        return {
            "status": "deleted",
            "message": ACCOUNT_DELETION_NOTICE,
        }
    except BillingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ActiveAccountJobsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Account deletion is unavailable while media processing is active. "
                "Wait for it to finish or cancel the job first."
            ),
        ) from exc
    except JobWorkspaceLockTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ErasureJournalError as exc:
        logger.error("Refusing account deletion because the erasure journal is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Privacy protection is temporarily unavailable. Please try again.",
        ) from exc
    except HTTPException:
        raise
    except Exception as e:
        safe_msg = sanitize_error(e)
        logger.error(f"Account deletion failed: {safe_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete account: {safe_msg}"
        )


GOOGLE_AUTH_NONCE_COOKIE_NAME = "gsubs_google_nonce"


class GoogleAuthNonce(BaseModel):
    nonce: str
    expires_in: int
    client_id: str


class GoogleLogin(BaseModel):
    id_token: str = Field(..., min_length=1, max_length=16_384)


def _google_nonce_cookie_settings() -> dict[str, Any]:
    return {
        "key": GOOGLE_AUTH_NONCE_COOKIE_NAME,
        "httponly": True,
        "secure": not settings.is_dev,
        "samesite": "lax",
        "path": "/",
    }


@router.get(
    "/google/nonce",
    response_model=GoogleAuthNonce,
    dependencies=[Depends(limiter_login)],
)
def get_google_auth_nonce(response: Response) -> Any:
    """Issue a nonce for a Google Identity Services sign-in attempt."""
    client_id = google_client_id()
    if not client_id:
        raise HTTPException(status_code=503, detail="Google login is not configured.")
    nonce = create_google_auth_nonce()
    response.set_cookie(
        value=google_auth_nonce_hash(nonce),
        max_age=settings.google_auth_nonce_ttl_seconds,
        **_google_nonce_cookie_settings(),
    )
    return {
        "nonce": nonce,
        "expires_in": settings.google_auth_nonce_ttl_seconds,
        "client_id": client_id,
    }


@router.post("/google", response_model=Token, dependencies=[Depends(limiter_login)])
def google_login(
    payload: GoogleLogin,
    request: Request,
    response: Response,
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
    promotion_store: LoginPromotionStore = Depends(get_login_promotion_store),
) -> Any:
    """Verify a Google ID token and issue a GSUBS session."""
    if not google_client_id():
        raise HTTPException(status_code=503, detail="Google login is not configured.")
    try:
        nonce_hash = request.cookies.get(GOOGLE_AUTH_NONCE_COOKIE_NAME)
        profile = verify_google_id_token(
            payload.id_token,
            expected_nonce_hash=nonce_hash,
            require_nonce=not settings.is_dev or bool(nonce_hash),
        )
        user = user_store.upsert_google_user(
            profile["email"],
            profile["name"],
            profile["sub"],
            profile.get("avatar_url"),
        )
    except GoogleAuthError as exc:
        logger.warning("Google login rejected: %s", sanitize_error(exc))
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    beta_credits_awarded = _claim_beta_login_credits(
        user=user,
        promotion_store=promotion_store,
    )
    token = session_store.issue_session(user, request.headers.get("user-agent"))
    response.delete_cookie(**_google_nonce_cookie_settings())
    _set_media_session_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name,
        "beta_credits_awarded": beta_credits_awarded,
    }
