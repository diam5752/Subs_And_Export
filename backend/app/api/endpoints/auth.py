from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from ...auth import UserStore, SessionStore, User
from ..deps import get_user_store, get_session_store, get_current_user

router = APIRouter()

class UserCreate(BaseModel):
    email: str
    password: str
    name: str

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

@router.post("/register", response_model=UserResponse)
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

@router.post("/token", response_model=Token)
def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""
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

class UserUpdateName(BaseModel):
    name: str

@router.put("/me", response_model=UserResponse)
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
    password: str
    confirm_password: str

@router.put("/password", response_model=Any)
def update_password(
    user_in: UserUpdatePassword,
    current_user: User = Depends(get_current_user),
    user_store: UserStore = Depends(get_user_store),
) -> Any:
    """Update current user password (local users only)."""
    if current_user.provider != "local":
        raise HTTPException(status_code=400, detail="Cannot update password for external provider")
    
    if user_in.password != user_in.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
        
    user_store.update_password(current_user.id, user_in.password)
    return {"status": "success"}


@router.delete("/me", response_model=Any)
def delete_account(
    current_user: User = Depends(get_current_user),
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
) -> Any:
    """Delete current user account and all associated data (GDPR compliance)."""
    try:
        # Revoke all sessions
        session_store.revoke_all_sessions(current_user.id)
        
        # Delete user (this should cascade to delete jobs, history, etc.)
        user_store.delete_user(current_user.id)
        
        return {"status": "deleted", "message": "Account and all data have been permanently deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete account: {str(e)}"
        )


# Google OAuth
import secrets
from ...auth import google_oauth_config, build_google_flow, exchange_google_code

class GoogleAuthURL(BaseModel):
    auth_url: str
    state: str

@router.get("/google/url", response_model=GoogleAuthURL)
def get_google_auth_url() -> Any:
    """Get Google OAuth URL for frontend to redirect to."""
    cfg = google_oauth_config()
    if not cfg:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    
    state = secrets.token_urlsafe(16)
    flow = build_google_flow(cfg)
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=state
    )
    return {"auth_url": auth_url, "state": state}


class GoogleCallback(BaseModel):
    code: str
    state: str

@router.post("/google/callback", response_model=Token)
def google_oauth_callback(
    callback: GoogleCallback,
    user_store: UserStore = Depends(get_user_store),
    session_store: SessionStore = Depends(get_session_store),
) -> Any:
    """Handle Google OAuth callback and issue session token."""
    cfg = google_oauth_config()
    if not cfg:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    
    try:
        profile = exchange_google_code(cfg, callback.code)
        user = user_store.upsert_google_user(
            profile["email"], profile["name"], profile.get("sub") or ""
        )
        token = session_store.issue_session(user)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user.id,
            "name": user.name
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Google auth failed: {str(e)}")
