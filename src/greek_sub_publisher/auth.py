"""Lightweight authentication helpers for Streamlit UI."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import config


@dataclass
class User:
    """Represents an authenticated user profile."""

    id: str
    email: str
    name: str
    provider: str  # "local" or "google"
    password_hash: str | None = None
    google_sub: str | None = None
    created_at: str | None = None

    def to_session(self) -> dict:
        """Compact dict safe to store in session_state."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "provider": self.provider,
        }


class UserStore:
    """Simple JSON-backed user store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.PROJECT_ROOT / "logs" / "users.json")

    # Internal helpers
    def _load(self) -> List[dict]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _write(self, rows: List[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)

    # Public API
    def register_local_user(self, email: str, password: str, name: str) -> User:
        email = email.strip().lower()
        if not email:
            raise ValueError("Email is required")
        if not password:
            raise ValueError("Password is required")
        existing = self.get_user_by_email(email)
        if existing:
            raise ValueError("User already exists")
        user = User(
            id=secrets.token_hex(8),
            email=email,
            name=name.strip() or email.split("@")[0],
            provider="local",
            password_hash=_hash_password(password),
            created_at=_utc_iso(),
        )
        rows = self._load()
        rows.append(asdict(user))
        self._write(rows)
        return user

    def upsert_google_user(self, email: str, name: str, sub: str) -> User:
        email = email.strip().lower()
        rows = self._load()
        for idx, row in enumerate(rows):
            if row.get("email") == email:
                # Update existing
                rows[idx]["name"] = name
                rows[idx]["google_sub"] = sub
                rows[idx]["provider"] = "google"
                self._write(rows)
                return _user_from_row(rows[idx])

        user = User(
            id=secrets.token_hex(8),
            email=email,
            name=name.strip() or email.split("@")[0],
            provider="google",
            google_sub=sub,
            created_at=_utc_iso(),
        )
        rows.append(asdict(user))
        self._write(rows)
        return user

    def authenticate_local(self, email: str, password: str) -> Optional[User]:
        email = email.strip().lower()
        user = self.get_user_by_email(email)
        if not user:
            return None
        if not user.password_hash:
            return None
        if _verify_password(password, user.password_hash):
            return user
        return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        email = email.strip().lower()
        for row in self._load():
            if row.get("email") == email:
                return _user_from_row(row)
        return None


def _user_from_row(row: Dict) -> User:
    return User(
        id=row.get("id") or secrets.token_hex(8),
        email=row.get("email", ""),
        name=row.get("name", "") or row.get("email", "User"),
        provider=row.get("provider", "local"),
        password_hash=row.get("password_hash"),
        google_sub=row.get("google_sub"),
        created_at=row.get("created_at"),
    )


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def _verify_password(password: str, encoded: str) -> bool:
    if "$" not in encoded:
        return False
    salt, digest = encoded.split("$", 1)
    return _hash_password(password, salt) == encoded and bool(digest)


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _get_secret(key: str) -> str | None:
    """Safely read a Streamlit secret if available."""
    try:
        import streamlit as st  # Local import to avoid hard dependency outside UI

        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets.get(key))
    except Exception:
        return None
    return None


def google_oauth_config() -> dict[str, str] | None:
    """
    Read Google OAuth configuration from environment or Streamlit secrets.

    Required:
        GOOGLE_CLIENT_ID
        GOOGLE_CLIENT_SECRET
        GOOGLE_REDIRECT_URI  (should point back to the running Streamlit app)
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID") or _get_secret("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or _get_secret(
        "GOOGLE_CLIENT_SECRET"
    )
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or _get_secret(
        "GOOGLE_REDIRECT_URI"
    )
    if not (client_id and client_secret and redirect_uri):
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def build_google_flow(cfg: dict[str, str]):
    """Create a Google OAuth Flow instance (import deferred)."""
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [cfg["redirect_uri"]],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
        redirect_uri=cfg["redirect_uri"],
    )
    return flow


def exchange_google_code(cfg: dict[str, str], code: str) -> dict:
    """Exchange OAuth code for a verified profile dict."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    flow = build_google_flow(cfg)
    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds or not creds.id_token:
        raise RuntimeError("Missing Google ID token")
    idinfo = id_token.verify_oauth2_token(
        creds.id_token, Request(), cfg["client_id"]
    )
    return {
        "email": idinfo.get("email"),
        "name": idinfo.get("name") or idinfo.get("email") or "Google User",
        "sub": idinfo.get("sub"),
    }
