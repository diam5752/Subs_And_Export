"""Lightweight authentication helpers shared across CLI and backend."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import tomllib

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
        _validate_password_strength(password)
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
                updated = conn.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (email,),
                ).fetchone()
                return _user_from_row(dict(updated)) if updated else _user_from_row(dict(row))

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
        _validate_password_strength(new_password)
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

    def delete_user(self, user_id: str) -> None:
        """Delete a user and all associated data (GDPR compliance)."""
        with self.db.connect() as conn:
            # Delete associated sessions
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            # Delete associated jobs
            conn.execute("DELETE FROM jobs WHERE user_id = ?", (user_id,))
            # Delete associated history
            conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
            # Delete the user
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


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

    def revoke_all_sessions(self, user_id: str) -> None:
        """Revoke all sessions for a user (for account deletion or security)."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


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
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    params = {
        "n": 2 ** 14,
        "r": 8,
        "p": 1,
        "dklen": 64,
    }
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt_bytes, **params)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        salt=salt_bytes.hex(),
        digest=digest.hex(),
        **params,
    )


def _hash_password_legacy(password: str, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(f"session:{token}".encode("utf-8")).hexdigest()


def _verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, stored = encoded.split("$", 5)
            salt_bytes = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(stored)
            derived = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt_bytes,
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(expected),
            )
            return hmac.compare_digest(derived, expected)
        except Exception:
            return False

    if "$" not in encoded:
        return False
    salt, digest = encoded.split("$", 1)
    legacy_hash = _hash_password_legacy(password, salt)
    return hmac.compare_digest(legacy_hash, encoded) and bool(digest)


def _validate_password_strength(password: str) -> None:
    """Enforce a minimum password policy for interactive accounts."""
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    has_letter = any(ch.isalpha() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    if not (has_letter and has_digit):
        raise ValueError("Password must include both letters and numbers")


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _get_secret(key: str) -> str | None:
    """Read a secret from environment or a local TOML file.

    The optional env var ``GSP_SECRETS_FILE`` can point to a specific secrets file.
    Set ``GSP_USE_FILE_SECRETS=0`` to skip the file fallback (useful in tests).
    """
    env_override = os.getenv(key)
    if env_override:
        return env_override

    if os.getenv("GSP_USE_FILE_SECRETS", "1") == "0":
        return None

    candidate = os.getenv("GSP_SECRETS_FILE")
    search_paths = []
    if candidate:
        search_paths.append(Path(candidate))
    search_paths.append(config.PROJECT_ROOT / "config" / "secrets.toml")

    for path in search_paths:
        try:
            if not path.exists():
                continue
            data = tomllib.loads(path.read_text())
            if key in data:
                return str(data[key])
        except Exception:
            return None
    return None


def google_oauth_config() -> dict[str, str] | None:
    """Read Google OAuth configuration from environment or a secrets file.

    Required:
        GOOGLE_CLIENT_ID
        GOOGLE_CLIENT_SECRET
        GOOGLE_REDIRECT_URI (should point back to the running frontend)
    """
    client_id = _get_secret("GOOGLE_CLIENT_ID")
    client_secret = _get_secret("GOOGLE_CLIENT_SECRET")
    redirect_uri = _get_secret("GOOGLE_REDIRECT_URI") or _derive_frontend_redirect()
    if not (client_id and client_secret and redirect_uri):
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def _derive_frontend_redirect() -> str | None:
    """Best-effort fallback to build a redirect URI from a frontend base URL."""
    base = (
        os.getenv("FRONTEND_URL")
        or os.getenv("NEXT_PUBLIC_SITE_URL")
        or os.getenv("NEXT_PUBLIC_APP_URL")
    )
    if not base:
        return None
    return base.rstrip("/") + "/login"


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
        raise ValueError("Missing Google ID token")
    idinfo = id_token.verify_oauth2_token(
        creds.id_token, Request(), cfg["client_id"]
    )
    return {
        "email": idinfo.get("email"),
        "name": idinfo.get("name") or idinfo.get("email") or "Google User",
        "sub": idinfo.get("sub"),
    }
