"""OAuth state storage and validation (CSRF protection)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from .database import Database

DEFAULT_OAUTH_STATE_TTL_SECONDS = 10 * 60  # 10 minutes


@dataclass(frozen=True, slots=True)
class OAuthState:
    state: str
    provider: str
    user_id: str | None
    created_at: int
    expires_at: int
    user_agent: str | None
    ip: str | None


class OAuthStateStore:
    """SQLite-backed store for short-lived OAuth state tokens."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def issue_state(
        self,
        *,
        provider: str,
        user_id: str | None,
        user_agent: str | None,
        ip: str | None,
        ttl_seconds: int = DEFAULT_OAUTH_STATE_TTL_SECONDS,
    ) -> str:
        state = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + max(30, ttl_seconds)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_states(state, provider, user_id, created_at, expires_at, user_agent, ip)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (state, provider, user_id, now, expires_at, user_agent, ip),
            )
            conn.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now,))
        return state

    def consume_state(
        self,
        *,
        provider: str,
        state: str,
        user_id: str | None,
        user_agent: str | None,
        ip: str | None,
    ) -> bool:
        now = int(time.time())
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT provider, user_id, expires_at, user_agent, ip
                FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()
            if not row:
                return False

            expires_at = int(row["expires_at"])
            if expires_at <= now:
                conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
                return False

            if str(row["provider"]) != provider:
                return False

            stored_user_id = row["user_id"]
            if stored_user_id is not None and stored_user_id != user_id:
                return False

            stored_ua = row["user_agent"]
            if stored_ua is not None and stored_ua != user_agent:
                return False

            stored_ip = row["ip"]
            if stored_ip is not None and stored_ip != ip:
                return False

            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            return True

