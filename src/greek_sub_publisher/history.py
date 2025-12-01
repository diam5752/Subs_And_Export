"""Per-user history logging for processing and publishing events."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List

from . import config
from .auth import User


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
    """Append-only JSONL store for user activity."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.PROJECT_ROOT / "logs" / "user_history.jsonl")

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
        self._append(asdict(event))
        return event

    def recent_for_user(self, user: User, limit: int = 20) -> List[HistoryEvent]:
        rows = self._read_all()
        filtered = [row for row in rows if row.get("user_id") == user.id]
        filtered = list(reversed(filtered))[:limit]
        return [
            HistoryEvent(
                ts=row.get("ts", ""),
                user_id=row.get("user_id", ""),
                email=row.get("email", ""),
                kind=row.get("kind", ""),
                summary=row.get("summary", ""),
                data=row.get("data", {}) or {},
            )
            for row in filtered
        ]

    # Internal helpers
    def _append(self, row: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")

    def _read_all(self) -> List[Dict]:
        if not self.path.exists():
            return []
        rows: List[Dict] = []
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []
        return rows


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
