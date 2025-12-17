from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core import config
from ...core.auth import User
from ...core.oauth_state import OAuthStateStore
from ...core.ratelimit import limiter_content, limiter_login
from ...services import tiktok
from ...services.history import HistoryStore
from ..deps import get_current_user, get_history_store, get_oauth_state_store

router = APIRouter()

class TikTokAuthURL(BaseModel):
    auth_url: str
    state: str

@router.get("/url", response_model=TikTokAuthURL)
def get_tiktok_auth_url(
    request: Request,
    current_user: User = Depends(get_current_user),
    oauth_state_store: OAuthStateStore = Depends(get_oauth_state_store),
) -> Any:
    """Get TikTok OAuth URL."""
    cfg = tiktok.config_from_env()
    if not cfg:
        raise HTTPException(status_code=503, detail="TikTok integration not configured")

    state = oauth_state_store.issue_state(
        provider="tiktok",
        user_id=current_user.id,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )

    url = tiktok.build_auth_url(cfg, state=state)
    return {"auth_url": url, "state": state}

class TikTokCallback(BaseModel):
    code: str = Field(..., max_length=4096)
    state: str = Field(..., max_length=1024)

@router.post("/callback", dependencies=[Depends(limiter_login)])
def tiktok_callback(
    payload: TikTokCallback,
    request: Request,
    current_user: User = Depends(get_current_user),
    history_store: HistoryStore = Depends(get_history_store),
    oauth_state_store: OAuthStateStore = Depends(get_oauth_state_store),
) -> Any:
    """Exchange code for TikTok tokens."""
    cfg = tiktok.config_from_env()
    if not cfg:
        raise HTTPException(status_code=503, detail="TikTok integration not configured")

    try:
        if not oauth_state_store.consume_state(
            provider="tiktok",
            state=payload.state,
            user_id=current_user.id,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        ):
            raise HTTPException(status_code=400, detail="Invalid OAuth state")

        tokens = tiktok.exchange_code_for_token(cfg, payload.code)

        # In a real app we might store these encrypted in DB
        # For this lightweight version we might return them to client or store in session?
        # The prompt implies we might store them in session state (frontend) or backend DB.
        # The history_ui.py suggests they were in session_state.
        # Let's return them so frontend can store them or use them.
        # OR we can store them in a 'connected_apps' table.
        # Given simplicity constraints, let's return them.

        history_store.record_event(
            current_user,
            "tiktok_auth",
            "Connected TikTok Account",
            {"obtained_at": tokens.obtained_at}
        )

        return tokens.as_dict()
    except tiktok.TikTokError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"TikTok auth failed: {str(e)}")

class TikTokUploadRequest(BaseModel):
    access_token: str = Field(..., max_length=4096)
    video_path: str = Field(..., max_length=1024) # Relative path on server
    title: str = Field(..., max_length=2200)
    description: str = Field(..., max_length=2200)

@router.post("/upload", dependencies=[Depends(limiter_content)])
def upload_video_tiktok(
    req: TikTokUploadRequest,
    current_user: User = Depends(get_current_user),
    history_store: HistoryStore = Depends(get_history_store)
) -> Any:
    """Upload a processed video to TikTok."""
    # Validate path prevents traversal
    # allow paths under config.PROJECT_ROOT / "data"

    data_dir = config.PROJECT_ROOT / "data"
    # Security check: ensure path is within data directory

    # Security check:
    full_path = (config.PROJECT_ROOT / req.video_path).resolve()
    try:
        full_path.relative_to(data_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid video path")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    # Construct fake tokens obj
    # In real app verify scopes/expiry
    tokens = tiktok.TikTokTokens(
        access_token=req.access_token,
        refresh_token=None,
        expires_in=3600,
        obtained_at=0
    )

    try:
        res = tiktok.upload_video(tokens, full_path, req.title, req.description)

        history_store.record_event(
            current_user,
            "tiktok_upload",
            f"Uploaded video: {req.title}",
            {"file": req.video_path, "response": res}
        )

        return res
    except tiktok.TikTokError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
