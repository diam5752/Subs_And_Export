import logging
from typing import Any

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
from ...core.cleanup import delete_job_workspace
from ...core.config import settings
from ...core.errors import sanitize_error
from ...core.ratelimit import limiter_auth_change, limiter_login, limiter_register, limiter_signup_daily
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.points import PointsStore
from ..deps import (
    get_current_user,
    get_history_store,
    get_job_store,
    get_points_store,
    get_session_store,
    get_user_store,
)

router = APIRouter()
logger = logging.getLogger(__name__)

class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
    name: str = Field(..., max_length=100)

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    name: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    provider: str

@router.post("/register", response_model=UserResponse, dependencies=[Depends(limiter_register), Depends(limiter_signup_daily)])
def register(
    user_in: UserCreate,
    user_store: UserStore = Depends(get_user_store)
) -> Any:
    """Register a new user."""
    try:
        user = user_store.register_local_user(
            email=user_in.email,
            password=user_in.password,
            name=user_in.name
        )
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/token", response_model=Token, dependencies=[Depends(limiter_login)])
def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
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

    token = session_store.issue_session(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name
    }

@router.get("/me", response_model=UserResponse)
def read_users_me(
    current_user: User = Depends(get_current_user)
) -> Any:
    """Get current user profile."""
    return current_user


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

    return {"status": "success"}



@router.get("/export", response_model=Any)
def export_my_data(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
) -> Any:
    """Export all personal data (GDPR Right to Access)."""
    # Profile
    profile = {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "created_at": current_user.created_at,
        "provider": current_user.provider,
    }

    # Jobs
    jobs = job_store.list_jobs_for_user(current_user.id)

    # History
    history = history_store.recent_for_user(current_user, limit=1000)

    return {
        "profile": profile,
        "jobs": jobs,
        "history": history
    }

@router.delete("/me", response_model=Any, dependencies=[Depends(limiter_auth_change)])
def delete_account(
    current_user: User = Depends(get_current_user),
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
    job_store: JobStore = Depends(get_job_store),
) -> Any:
    """Delete current user account and all associated data (GDPR compliance)."""
    try:
        # 1. Cleanup Filesystem Artifacts
        # Get all jobs to find their files
        jobs = job_store.list_jobs_for_user(current_user.id)

        data_dir = settings.data_dir
        uploads_dir = data_dir / "uploads"
        artifacts_root = data_dir / "artifacts"

        for job in jobs:
            delete_job_workspace(
                job_id=job.id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_root,
            )

        # 2. Revoke all sessions
        session_store.revoke_all_sessions(current_user.id)

        # 3. Delete user (cascades to DB jobs/history)
        user_store.delete_user(current_user.id)

        return {"status": "deleted", "message": "Account and all data have been permanently deleted"}
    except Exception as e:
        safe_msg = sanitize_error(e)
        logger.error(f"Account deletion failed: {safe_msg}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete account: {safe_msg}"
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
        )
    except GoogleAuthError as exc:
        logger.warning("Google login rejected: %s", sanitize_error(exc))
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token = session_store.issue_session(user, request.headers.get("user-agent"))
    response.delete_cookie(**_google_nonce_cookie_settings())
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name,
    }
