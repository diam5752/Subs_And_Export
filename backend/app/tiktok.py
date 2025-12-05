"""TikTok OAuth + upload helpers."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode

import requests


AUTH_URL = "https://www.tiktok.com/auth/authorize/"
TOKEN_URL = "https://open-api.tiktok.com/oauth/access_token/"
REFRESH_URL = "https://open-api.tiktok.com/oauth/refresh_token/"
UPLOAD_URL = "https://open-api.tiktok.com/share/video/upload/"
DEFAULT_SCOPE = "user.info.basic,video.upload"


class TikTokError(RuntimeError):
    """Raised when TikTok API responds with an error."""


@dataclass
class TikTokTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int
    obtained_at: float

    def is_expired(self) -> bool:
        return time.time() >= (self.obtained_at + max(self.expires_in - 60, 0))

    def as_dict(self) -> Dict:
        return asdict(self)


def config_from_env() -> Optional[dict]:
    """Pull TikTok client credentials from environment variables."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    redirect_uri = os.getenv("TIKTOK_REDIRECT_URI")
    if not (client_key and client_secret and redirect_uri):
        return None
    return {
        "client_key": client_key,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def build_auth_url(cfg: dict, state: str, scope: str | None = None) -> str:
    params = {
        "client_key": cfg["client_key"],
        "response_type": "code",
        "scope": scope or DEFAULT_SCOPE,
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(cfg: dict, code: str) -> TikTokTokens:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_key": cfg["client_key"],
            "client_secret": cfg["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": cfg["redirect_uri"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or {}
    access_token = data.get("access_token")
    if not access_token:
        raise TikTokError(f"TikTok token exchange failed: {payload}")
    return TikTokTokens(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 0) or 0),
        obtained_at=time.time(),
    )


def refresh_access_token(cfg: dict, refresh_token: str) -> TikTokTokens:
    resp = requests.post(
        REFRESH_URL,
        data={
            "client_key": cfg["client_key"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or {}
    access_token = data.get("access_token")
    if not access_token:
        raise TikTokError(f"TikTok refresh failed: {payload}")
    return TikTokTokens(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 0) or 0),
        obtained_at=time.time(),
    )


def upload_video(
    tokens: TikTokTokens,
    video_path: Path,
    title: str,
    description: str,
) -> Dict:
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found for upload: {video_path}")

    with video_path.open("rb") as fh:
        files = {"video": fh}
        resp = requests.post(
            UPLOAD_URL,
            data={
                "access_token": tokens.access_token,
                "title": title[:220],
                "text": description[:2200],
            },
            files=files,
            timeout=120,
        )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or {}
    if data.get("error_code") not in (None, 0):
        raise TikTokError(f"TikTok upload error: {payload}")
    return data
