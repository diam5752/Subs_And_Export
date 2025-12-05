"""Lightweight authentication helpers for Streamlit UI."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional

from . import config
from .database import Database


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
    """SQLite-backed user store suitable for multi-user deployments."""

    def __init__(self, path: str | os.PathLike | None = None, db: Database | None = None) -> None:
        self.db = db or Database(path)

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
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(id, email, name, provider, password_hash, google_sub, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.email,
                    user.name,
                    user.provider,
                    user.password_hash,
                    user.google_sub,
                    user.created_at,
                ),
            )
        return user

    def upsert_google_user(self, email: str, name: str, sub: str) -> User:
        email = email.strip().lower()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET name = ?, google_sub = ?, provider = ? WHERE email = ?",
                    (name, sub, "google", email),
                )
                return _user_from_row(dict(row))

            user = User(
                id=secrets.token_hex(8),
                email=email,
                name=name.strip() or email.split("@")[0],
                provider="google",
                google_sub=sub,
                created_at=_utc_iso(),
            )
            conn.execute(
                """
                INSERT INTO users(id, email, name, provider, google_sub, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.email,
                    user.name,
                    user.provider,
                    user.google_sub,
                    user.created_at,
                ),
            )
            return user


    
    def update_name(self, user_id: str, new_name: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE users SET name = ? WHERE id = ?",
                (new_name.strip(), user_id),
            )

    def update_password(self, user_id: str, new_password: str) -> None:
        p_hash = _hash_password(new_password)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (p_hash, user_id),
            )

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
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return None
        return _user_from_row(dict(row))


class SessionStore:
    """Persistent session tokens for automatic sign-in."""

    SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def issue_session(self, user: User, user_agent: str | None = None) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        now = int(time.time())
        expires_at = now + self.SESSION_TTL_SECONDS
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions(token_hash, user_id, created_at, expires_at, user_agent)
                VALUES(?, ?, ?, ?, ?)
                """,
                (token_hash, user.id, now, expires_at, user_agent),
            )
        return token

    def authenticate(self, token: str) -> Optional[User]:
        if not token:
            return None
        token_hash = _hash_token(token)
        now = int(time.time())
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT u.* FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                ORDER BY s.created_at DESC
                LIMIT 1
                """,
                (token_hash, now),
            ).fetchone()
        if not row:
            return None
        return _user_from_row(dict(row))

    def revoke(self, token: str) -> None:
        token_hash = _hash_token(token)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


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


def _hash_token(token: str) -> str:
    return hashlib.sha256(f"session:{token}".encode("utf-8")).hexdigest()


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
