"""OAuth state storage and validation (CSRF protection)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from sqlalchemy import delete, select

from ..db.models import DbOAuthState
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
        with self.db.session() as session:
            session.add(
                DbOAuthState(
                    state=state,
                    provider=provider,
                    user_id=user_id,
                    created_at=now,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip=ip,
                )
            )
            session.execute(delete(DbOAuthState).where(DbOAuthState.expires_at <= now))
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
        with self.db.session() as session:
            row = session.scalar(select(DbOAuthState).where(DbOAuthState.state == state).limit(1))
            if not row:
                return False

            if int(row.expires_at) <= now:
                session.execute(delete(DbOAuthState).where(DbOAuthState.state == state))
                return False

            if str(row.provider) != provider:
                return False

            if row.user_id is not None and row.user_id != user_id:
                return False

            if row.user_agent is not None and row.user_agent != user_agent:
                return False

            if row.ip is not None and row.ip != ip:
                return False

            session.execute(delete(DbOAuthState).where(DbOAuthState.state == state))
            return True
