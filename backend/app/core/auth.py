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
from typing import Any, TypedDict, cast
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import DbDeletedEmail, DbSession, DbUser
from ..services.points import PointsStore
from .config import settings
from .database import Database

logger = logging.getLogger(__name__)

DELETED_EMAIL_RETENTION_DAYS = 365
DELETED_EMAIL_RETENTION_SECONDS = DELETED_EMAIL_RETENTION_DAYS * 24 * 60 * 60
DELETED_EMAIL_MARKER_PURPOSE = "prevent_repeat_signup_credit_grants"


class GoogleAuthError(ValueError):
    """A public-safe Google authentication failure."""


class GoogleProfile(TypedDict):
    """Verified, normalized Google profile fields safe for persistence."""

    email: str
    name: str
    sub: str
    avatar_url: str | None


@dataclass(slots=True)
class User:
    """Represents an authenticated user profile."""

    id: str
    email: str
    name: str
    provider: str  # "local" or "google"
    password_hash: str | None = None
    google_sub: str | None = None
    avatar_url: str | None = None
    created_at: str | None = None
    email_verified: bool = False

    def to_session(self) -> dict[str, str]:
        """Compact dict safe to store in session_state."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "provider": self.provider,
        }


class UserStore:
    """PostgreSQL-backed user store suitable for multi-user deployments."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # Public API
    def register_local_user(self, email: str, password: str, name: str) -> User:
        email = email.strip().lower()
        if not email:
            raise ValueError("Email is required")
        _validate_email(email)
        if not password:
            raise ValueError("Password is required")
        _validate_password_strength(password)

        # Service-layer name validation
        final_name = name.strip()
        if final_name:
            _validate_name(final_name)
        else:
            final_name = email.split("@")[0][:100]

        existing = self.get_user_by_email(email)
        if existing:
            raise ValueError("User already exists")
        deleted_email = self._email_was_deleted(email)
        user = User(
            id=secrets.token_hex(8),
            email=email,
            name=final_name,
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
                        email_verified=False,  # Local users need to verify email
                    )
                )
        except IntegrityError as exc:
            raise ValueError("User already exists") from exc

        PointsStore(db=self.db).ensure_account(
            user.id,
            email_verified=user.email_verified,
            starting_balance_override=0 if deleted_email else None,
        )
        return user

    def upsert_google_user(
        self,
        email: str,
        name: str,
        sub: str,
        avatar_url: str | None = None,
    ) -> User:
        email = email.strip().lower()
        _validate_email(email)
        sub = sub.strip()
        if not sub:
            raise GoogleAuthError("Google token subject is missing.")
        if len(sub) > 255:
            raise GoogleAuthError("Google token subject is too long.")
        normalized_avatar_url = _normalize_google_avatar_url(avatar_url)
        # Truncate name for external providers (don't fail)
        final_name = (name.strip() or email.split("@")[0])[:100]
        created = False
        deleted_email = False
        try:
            with self.db.session() as session:
                existing_identity = session.scalar(select(DbUser).where(DbUser.google_sub == sub).limit(1))
                if existing_identity:
                    existing_identity.name = final_name
                    existing_identity.email_verified = True
                    if normalized_avatar_url is not None:
                        existing_identity.avatar_url = normalized_avatar_url
                    session.flush()
                    user = _user_from_db(existing_identity)
                else:
                    existing_email = session.scalar(select(DbUser).where(DbUser.email == email).limit(1))
                    if existing_email:
                        raise GoogleAuthError(
                            "Google login cannot automatically link an existing email. "
                            "Log in with the existing account before linking Google."
                        )
                    deleted_email = self._email_was_deleted(email, session=session)
                    user = User(
                        id=secrets.token_hex(8),
                        email=email,
                        name=final_name,
                        provider="google",
                        google_sub=sub,
                        avatar_url=normalized_avatar_url,
                        created_at=_utc_iso(),
                        email_verified=True,
                    )
                    session.add(
                        DbUser(
                            id=user.id,
                            email=user.email,
                            name=user.name,
                            provider=user.provider,
                            password_hash=None,
                            google_sub=user.google_sub,
                            avatar_url=user.avatar_url,
                            created_at=user.created_at,
                            email_verified=True,
                        )
                    )
                    created = True
        except IntegrityError as exc:
            raise GoogleAuthError("Google account could not be linked safely.") from exc

        if created:
            PointsStore(db=self.db).ensure_account(
                user.id,
                email_verified=user.email_verified,
                starting_balance_override=0 if deleted_email else None,
            )
        return user

    def update_name(self, user_id: str, new_name: str) -> None:
        clean_name = new_name.strip()
        _validate_name(clean_name)
        with self.db.session() as session:
            user = session.get(DbUser, user_id)
            if not user:
                return
            user.name = clean_name

    def update_password(self, user_id: str, new_password: str) -> None:
        _validate_password_strength(new_password)
        p_hash = _hash_password(new_password)
        with self.db.session() as session:
            user = session.get(DbUser, user_id)
            if not user:
                return
            user.password_hash = p_hash

    def authenticate_local(self, email: str, password: str) -> User | None:
        email = email.strip().lower()
        user = self.get_user_by_email(email)

        # Constant-time verification logic to prevent user enumeration.
        # We always perform a password verification, even if the user is not found.
        target_hash = user.password_hash if (user and user.password_hash) else _DUMMY_HASH
        is_valid = _verify_password(password, target_hash)

        if user and user.password_hash and is_valid:
            return user
        return None

    def get_user_by_email(self, email: str) -> User | None:
        email = email.strip().lower()
        with self.db.session() as session:
            user = session.scalar(select(DbUser).where(DbUser.email == email).limit(1))
            if not user:
                return None
            return _user_from_db(user)

    def delete_user(self, user_id: str) -> None:
        """Delete a user and all associated data (GDPR compliance)."""
        with self.db.session() as session:
            self.delete_user_in_session(session, user_id)

    def delete_user_in_session(
        self,
        session: Session,
        user_id: str,
    ) -> None:
        """Delete a user inside a caller-owned atomic workflow."""
        user = session.get(DbUser, user_id)
        if not user:
            return
        self._record_deleted_email(session, user.email or "")
        session.delete(user)

    def _email_was_deleted(self, email: str, *, session: Session | None = None) -> bool:
        if session:
            return (
                self._deleted_email_marker(
                    session,
                    email,
                    now=int(time.time()),
                )
                is not None
            )
        with self.db.session() as local_session:
            return (
                self._deleted_email_marker(
                    local_session,
                    email,
                    now=int(time.time()),
                )
                is not None
            )

    def deleted_email_marker_for_email(
        self,
        email: str,
    ) -> dict[str, str | int] | None:
        """Return the bounded, pseudonymous marker associated with an email."""
        with self.db.session() as session:
            marker = self._deleted_email_marker(
                session,
                email,
                now=int(time.time()),
            )
            if marker is None:
                return None
            return {
                "fingerprint": marker.email_hash,
                "fingerprint_algorithm": "sha256_normalized_email",
                "deleted_at": marker.deleted_at,
                "expires_at": marker.deleted_at + DELETED_EMAIL_RETENTION_SECONDS,
                "purpose": DELETED_EMAIL_MARKER_PURPOSE,
            }

    def cleanup_expired_deleted_email_markers(
        self,
        *,
        now: int | None = None,
    ) -> int:
        """Delete normalized-email hashes after the documented retention period."""
        current_time = int(time.time()) if now is None else now
        cutoff = current_time - DELETED_EMAIL_RETENTION_SECONDS
        with self.db.session() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(DbDeletedEmail).where(
                        DbDeletedEmail.deleted_at <= cutoff,
                    )
                ),
            )
            return int(result.rowcount or 0)

    def _record_deleted_email(self, session: Session, email: str) -> None:
        email_hash = _email_fingerprint(email)
        now = int(time.time())
        session.execute(
            delete(DbDeletedEmail).where(
                DbDeletedEmail.deleted_at <= (now - DELETED_EMAIL_RETENTION_SECONDS),
            )
        )
        session.merge(
            DbDeletedEmail(
                email_hash=email_hash,
                deleted_at=now,
            )
        )

    @staticmethod
    def _deleted_email_marker(
        session: Session,
        email: str,
        *,
        now: int,
    ) -> DbDeletedEmail | None:
        marker = session.get(DbDeletedEmail, _email_fingerprint(email))
        if marker is None:
            return None
        if marker.deleted_at + DELETED_EMAIL_RETENTION_SECONDS <= now:
            session.delete(marker)
            return None
        return marker


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

    def authenticate(self, token: str) -> User | None:
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
        avatar_url=getattr(user, "avatar_url", None),
        created_at=user.created_at,
        email_verified=getattr(user, "email_verified", False),
    )


def _hash_password(password: str, salt: str | None = None) -> str:
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    params = {
        "n": 2**14,
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


def _hash_token(token: str) -> str:
    return hashlib.sha256(f"session:{token}".encode("utf-8")).hexdigest()


def _verify_password(password: str, encoded: str) -> bool:
    supported_format = encoded.startswith("scrypt$")
    candidate = encoded if supported_format else _DUMMY_HASH
    try:
        _, n, r, p, salt_hex, stored = candidate.split("$", 5)
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
        return supported_format and hmac.compare_digest(derived, expected)
    except (TypeError, ValueError) as exc:
        logger.warning("Scrypt verification failed: %s", exc)
        if candidate != _DUMMY_HASH:
            _verify_password(password, _DUMMY_HASH)
        return False


def _validate_password_strength(password: str) -> None:
    """Enforce a minimum password policy for interactive accounts."""
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters long")
    has_letter = any(ch.isalpha() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    if not (has_letter and has_digit):
        raise ValueError("Password must include both letters and numbers")


def _email_fingerprint(email: str) -> str:
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validate_email(email: str) -> None:
    """Validate email format using regex."""
    if len(email) > 255:
        raise ValueError("Email must be at most 255 characters long")
    # Basic regex to catch obvious non-emails.
    # We avoid complex RFC compliance regexes to keep it simple and safe.
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, email):
        raise ValueError("Invalid email format")


def _validate_name(name: str) -> None:
    """Enforce name length limit."""
    if len(name) > 100:
        raise ValueError("Name must be at most 100 characters long")


def _normalize_google_avatar_url(value: str | None) -> str | None:
    """Accept only Google's HTTPS profile-image host."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 2_048:
        return None
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "lh3.googleusercontent.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        return None
    return candidate


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
    search_paths.append(settings.project_root / "config" / "secrets.toml")

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


def google_client_id() -> str | None:
    """Return the public Google Identity Services client ID, if configured."""
    value = _get_secret("GOOGLE_CLIENT_ID")
    return value.strip() if value and value.strip() else None


def create_google_auth_nonce() -> str:
    """Create an unpredictable nonce for a single Google sign-in attempt."""
    return secrets.token_urlsafe(32)


def google_auth_nonce_hash(nonce: str) -> str:
    """Hash a browser-visible nonce before storing it in an HttpOnly cookie."""
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _assert_google_nonce(
    payload: dict[str, Any],
    *,
    expected_nonce_hash: str | None,
    require_nonce: bool,
) -> None:
    token_nonce = str(payload.get("nonce") or "")
    if not expected_nonce_hash:
        if require_nonce:
            raise GoogleAuthError("Google login nonce is required.")
        return
    if not token_nonce or not hmac.compare_digest(
        google_auth_nonce_hash(token_nonce),
        expected_nonce_hash,
    ):
        raise GoogleAuthError("Google login nonce could not be verified.")


def _assert_google_payload_claims(
    payload: dict[str, Any],
    *,
    client_id: str,
) -> GoogleProfile:
    if payload.get("aud") != client_id:
        raise GoogleAuthError("Google token audience is not allowed.")
    if payload.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleAuthError("Google token issuer is not allowed.")
    if payload.get("email_verified") not in {True, "true", "True", "1"}:
        raise GoogleAuthError("Google email must be verified.")

    raw_sub = payload.get("sub")
    sub = raw_sub.strip() if isinstance(raw_sub, str) else ""
    if not sub:
        raise GoogleAuthError("Google token subject is missing.")
    if len(sub) > 255:
        raise GoogleAuthError("Google token subject is too long.")

    exp = payload.get("exp")
    if exp is None:
        raise GoogleAuthError("Google token expiry is missing.")
    try:
        exp_timestamp = int(exp)
    except (TypeError, ValueError) as exc:
        raise GoogleAuthError("Google token expiry is invalid.") from exc
    if exp_timestamp <= int(time.time()):
        raise GoogleAuthError("Google token has expired.")

    raw_email = payload.get("email")
    if not isinstance(raw_email, str) or not raw_email.strip():
        raise GoogleAuthError("Google profile is missing an email address.")
    email = raw_email.strip().lower()
    try:
        _validate_email(email)
    except ValueError as exc:
        raise GoogleAuthError("Google profile email is invalid.") from exc

    raw_name = payload.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else email
    raw_avatar_url = payload.get("picture")
    avatar_url = _normalize_google_avatar_url(raw_avatar_url) if isinstance(raw_avatar_url, str) else None
    return {
        "email": email,
        "name": name[:100],
        "sub": sub,
        "avatar_url": avatar_url,
    }


def verify_google_id_token(
    token: str,
    *,
    expected_nonce_hash: str | None,
    require_nonce: bool,
) -> GoogleProfile:
    """Verify a Google Identity Services ID token and return a safe profile."""
    if not token:
        raise GoogleAuthError("Google ID token is required.")
    if len(token) > 16_384:
        raise GoogleAuthError("Google ID token is too large.")
    client_id = google_client_id()
    if not client_id:
        raise GoogleAuthError("Google login is not configured.")

    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import id_token as google_id_token

    class TimeoutRequest(GoogleAuthRequest):
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("timeout", 30)
            return super().__call__(*args, **kwargs)  # type: ignore[no-untyped-call]

    try:
        raw_payload = google_id_token.verify_token(
            token,
            TimeoutRequest(),
            client_id,
            certs_url=settings.google_oauth_certs_url,
            clock_skew_in_seconds=30,
        )
    except Exception as exc:
        raise GoogleAuthError("Google token could not be verified.") from exc
    payload = dict(raw_payload)
    _assert_google_nonce(
        payload,
        expected_nonce_hash=expected_nonce_hash,
        require_nonce=require_nonce,
    )
    return _assert_google_payload_claims(payload, client_id=client_id)
