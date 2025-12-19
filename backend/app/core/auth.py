"""Lightweight authentication helpers shared across CLI and backend."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ..db.models import DbSession, DbUser
from ..services.points import PointsStore
from . import config
from .database import Database

logger = logging.getLogger(__name__)


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
        _validate_email(email)
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
        try:
            with self.db.session() as session:
                session.add(
                    DbUser(
                        id=user.id,
                        email=user.email,
                        name=user.name,
                        provider=user.provider,
                        password_hash=user.password_hash,
                        google_sub=user.google_sub,
                        created_at=user.created_at,
                    )
                )
        except IntegrityError as exc:
            raise ValueError("User already exists") from exc

        PointsStore(db=self.db).ensure_account(user.id)
        return user

    def upsert_google_user(self, email: str, name: str, sub: str) -> User:
        email = email.strip().lower()
        created = False
        with self.db.session() as session:
            existing = session.scalar(select(DbUser).where(DbUser.email == email).limit(1))
            if existing:
                existing.name = name.strip() or email.split("@")[0]
                existing.google_sub = sub
                existing.provider = "google"
                existing.password_hash = None
                session.flush()
                user = _user_from_db(existing)
            else:
                user = User(
                    id=secrets.token_hex(8),
                    email=email,
                    name=name.strip() or email.split("@")[0],
                    provider="google",
                    google_sub=sub,
                    created_at=_utc_iso(),
                )
                session.add(
                    DbUser(
                        id=user.id,
                        email=user.email,
                        name=user.name,
                        provider=user.provider,
                        password_hash=None,
                        google_sub=user.google_sub,
                        created_at=user.created_at,
                    )
                )
                created = True

        if created:
            PointsStore(db=self.db).ensure_account(user.id)
        return user

    def update_name(self, user_id: str, new_name: str) -> None:
        with self.db.session() as session:
            user = session.get(DbUser, user_id)
            if not user:
                return
            user.name = new_name.strip()

    def update_password(self, user_id: str, new_password: str) -> None:
        _validate_password_strength(new_password)
        p_hash = _hash_password(new_password)
        with self.db.session() as session:
            user = session.get(DbUser, user_id)
            if not user:
                return
            user.password_hash = p_hash

    def authenticate_local(self, email: str, password: str) -> Optional[User]:
        email = email.strip().lower()
        user = self.get_user_by_email(email)

        # Constant-time verification logic to prevent user enumeration.
        # We always perform a password verification, even if the user is not found.
        target_hash = user.password_hash if (user and user.password_hash) else _DUMMY_HASH
        is_valid = _verify_password(password, target_hash)

        if user and user.password_hash and is_valid:
            return user
        return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        email = email.strip().lower()
        with self.db.session() as session:
            user = session.scalar(select(DbUser).where(DbUser.email == email).limit(1))
            if not user:
                return None
            return _user_from_db(user)

    def delete_user(self, user_id: str) -> None:
        """Delete a user and all associated data (GDPR compliance)."""
        with self.db.session() as session:
            user = session.get(DbUser, user_id)
            if not user:
                return
            session.delete(user)


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
        with self.db.session() as session:
            session.merge(
                DbSession(
                    token_hash=token_hash,
                    user_id=user.id,
                    created_at=now,
                    expires_at=expires_at,
                    user_agent=user_agent,
                )
            )
        return token

    def authenticate(self, token: str) -> Optional[User]:
        if not token:
            return None
        token_hash = _hash_token(token)
        now = int(time.time())
        with self.db.session() as session:
            stmt = (
                select(DbUser)
                .join(DbSession, DbSession.user_id == DbUser.id)
                .where(DbSession.token_hash == token_hash, DbSession.expires_at > now)
                .order_by(DbSession.created_at.desc())
                .limit(1)
            )
            user = session.scalar(stmt)
            if not user:
                return None
            return _user_from_db(user)

    def revoke(self, token: str) -> None:
        token_hash = _hash_token(token)
        with self.db.session() as session:
            session.execute(delete(DbSession).where(DbSession.token_hash == token_hash))

    def revoke_all_sessions(self, user_id: str) -> None:
        """Revoke all sessions for a user (for account deletion or security)."""
        with self.db.session() as session:
            session.execute(delete(DbSession).where(DbSession.user_id == user_id))


def _user_from_db(user: DbUser) -> User:
    return User(
        id=user.id or secrets.token_hex(8),
        email=user.email or "",
        name=user.name or user.email or "User",
        provider=user.provider or "local",
        password_hash=user.password_hash,
        google_sub=user.google_sub,
        created_at=user.created_at,
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


# Constant-time verification fallback
_DUMMY_HASH = _hash_password("dummy_password")


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
        except Exception as e:
            logger.warning(f"Scrypt verification failed: {e}")
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


def _validate_email(email: str) -> None:
    """Validate email format using regex."""
    # Basic regex to catch obvious non-emails.
    # We avoid complex RFC compliance regexes to keep it simple and safe.
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, email):
        raise ValueError("Invalid email format")


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
        except Exception as e:
            logger.warning(f"Failed to read secrets file: {e}")
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

    # Enforce timeout on cert verification requests (default is infinite)
    class TimeoutRequest(Request):
        def __call__(self, *args, **kwargs):
            kwargs.setdefault("timeout", 30)
            return super().__call__(*args, **kwargs)

    flow = build_google_flow(cfg)
    # Enforce timeout on token exchange
    flow.fetch_token(code=code, timeout=30)
    creds = flow.credentials
    if not creds or not creds.id_token:
        raise ValueError("Missing Google ID token")
    idinfo = id_token.verify_oauth2_token(
        creds.id_token, TimeoutRequest(), cfg["client_id"]
    )
    return {
        "email": idinfo.get("email"),
        "name": idinfo.get("name") or idinfo.get("email") or "Google User",
        "sub": idinfo.get("sub"),
    }
