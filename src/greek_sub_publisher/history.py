"""Per-user history logging for processing and publishing events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from . import config
from .auth import User
from backend.app.database import Database


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
    """SQLite-backed append-only store for user activity."""

    def __init__(self, path: str | None = None, db: Database | None = None) -> None:
        self.db = db or Database(path or (config.PROJECT_ROOT / "logs" / "app.db"))

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
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users(id, email, name, provider, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.email,
                    user.name,
                    user.provider,
                    user.created_at or event.ts,
                ),
            )
            conn.execute(
                """
                INSERT INTO history(ts, user_id, email, kind, summary, data)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    event.ts,
                    event.user_id,
                    event.email,
                    event.kind,
                    event.summary,
                    self.db.dumps(event.data),
                ),
            )
        return event

    def recent_for_user(self, user: User, limit: int = 20) -> List[HistoryEvent]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, user_id, email, kind, summary, data
                FROM history
                WHERE user_id = ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (user.id, limit),
            ).fetchall()
        return [
            HistoryEvent(
                ts=row["ts"],
                user_id=row["user_id"],
                email=row["email"],
                kind=row["kind"],
                summary=row["summary"],
                data=self.db.loads(row["data"]),
            )
            for row in rows
        ]


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
