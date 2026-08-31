import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

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
from ...services.account_data_export import build_account_data_export
from ...services.account_erasure import ActiveAccountJobsError, erase_account_and_media
from ...services.billing import BillingConflictError, BillingService
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
    return build_account_data_export(
        current_user=current_user,
        job_store=job_store,
        history_store=history_store,
        db=db,
    )


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
