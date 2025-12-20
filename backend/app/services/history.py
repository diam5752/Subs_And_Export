"""Per-user history logging for processing and publishing events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from sqlalchemy import select

from ..core.auth import User
from ..core.database import Database
from ..db.models import DbHistoryEvent, DbUser


@dataclass
class HistoryEvent:
    """Lightweight user event for UI display."""

    ts: str
    user_id: str
    email: str
    kind: str  # e.g., "process", "tiktok_upload"
    summary: str
    data: Dict


class HistoryStore:
    """PostgreSQL-backed append-only store for user activity."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def record_event(
        self,
        user: User,
        kind: str,
        summary: str,
        data: Dict,
    ) -> HistoryEvent:
        event = HistoryEvent(
            ts=_utc_iso(),
            user_id=user.id,
            email=user.email,
            kind=kind,
            summary=summary,
            data=data,
        )
        with self.db.session() as session:
            existing_user = session.get(DbUser, user.id)
            if not existing_user:
                session.add(
                    DbUser(
                        id=user.id,
                        email=user.email,
                        name=user.name,
                        provider=user.provider,
                        password_hash=None,
                        google_sub=None,
                        created_at=user.created_at or event.ts,
                    )
                )
                session.flush()

            session.add(
                DbHistoryEvent(
                    ts=event.ts,
                    user_id=event.user_id,
                    email=event.email,
                    kind=event.kind,
                    summary=event.summary,
                    data=event.data,
                )
            )
        return event

    def recent_for_user(self, user: User, limit: int = 20) -> List[HistoryEvent]:
        with self.db.session() as session:
            stmt = (
                select(DbHistoryEvent)
                .where(DbHistoryEvent.user_id == user.id)
                .order_by(DbHistoryEvent.ts.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt).all())
        return [
            HistoryEvent(
                ts=row.ts,
                user_id=row.user_id,
                email=row.email,
                kind=row.kind,
                summary=row.summary,
                data=row.data,
            )
            for row in rows
        ]


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
