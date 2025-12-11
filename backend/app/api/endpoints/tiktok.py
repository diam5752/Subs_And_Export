import shutil
import uuid
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel

from ...services import tiktok
from ...core import config
from ...core.auth import User, UserStore, SessionStore
from ...services.history import HistoryStore
from ..deps import get_current_user, get_user_store, get_history_store

router = APIRouter()

class TikTokAuthURL(BaseModel):
    auth_url: str
    state: str

@router.get("/url", response_model=TikTokAuthURL)
def get_tiktok_auth_url(
    current_user: User = Depends(get_current_user)
) -> Any:
    """Get TikTok OAuth URL."""
    cfg = tiktok.config_from_env()
    if not cfg:
        raise HTTPException(status_code=503, detail="TikTok integration not configured")
    
    state = secrets.token_urlsafe(16)
    # Ideally store state in redis/db bound to session, but for now we rely on client echoing it back signed
    # or just simple match if stateless. Here we just return it.
    
    url = tiktok.build_auth_url(cfg, state=state)
    return {"auth_url": url, "state": state}

class TikTokCallback(BaseModel):
    code: str
    state: str

@router.post("/callback")
def tiktok_callback(
    payload: TikTokCallback,
    current_user: User = Depends(get_current_user),
    history_store: HistoryStore = Depends(get_history_store)
) -> Any:
    """Exchange code for TikTok tokens."""
    cfg = tiktok.config_from_env()
    if not cfg:
        raise HTTPException(status_code=503, detail="TikTok integration not configured")
        
    try:
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
    access_token: str
    video_path: str # Relative path on server
    title: str
    description: str

@router.post("/upload")
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
    if not str(full_path).startswith(str(data_dir.resolve())):
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
