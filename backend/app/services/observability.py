"""Privacy-bounded first-party operational observability."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_MAX_RECORDS = 20_000
_MAX_RECENT = 50
_COMPACT_INTERVAL_SECONDS = 3_600


@dataclass(frozen=True, slots=True)
class Presence:
    auth_state: str
    account_key: str | None
    route: str
    viewport: str
    seen_at: int


class ObservabilityStore:
    """Store anonymous allowlisted events and runtime-only presence."""

    def __init__(
        self,
        *,
        data_dir: Path,
        enabled: bool,
        retention_hours: int,
        presence_ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.enabled = enabled
        self.retention_hours = retention_hours
        self.presence_ttl_seconds = presence_ttl_seconds
        self._clock = clock
        self._salt = secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._presence: dict[str, Presence] = {}
        self._last_compacted_at = 0
        self._directory = data_dir / "observability"
        self._path = self._directory / "events.jsonl"
        if enabled:
            self._prepare_storage()

    @property
    def path(self) -> Path:
        return self._path

    def _prepare_storage(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)
        if not self._path.exists():
            self._path.touch(mode=0o600)
        os.chmod(self._path, 0o600)

    def _runtime_key(self, namespace: str, value: str) -> str:
        identity = f"{namespace}:{value}"
        return hashlib.sha256(self._salt + identity.encode("utf-8")).hexdigest()

    def record_presence(
        self,
        *,
        presence_id: str,
        user_id: str | None,
        route: str,
        viewport: str,
    ) -> None:
        if not self.enabled:
            return
        now = int(self._clock())
        key = self._runtime_key("session", presence_id)
        presence = Presence(
            auth_state="authenticated" if user_id is not None else "guest",
            account_key=(
                self._runtime_key("account", user_id)
                if user_id is not None
                else None
            ),
            route=route,
            viewport=viewport,
            seen_at=now,
        )
        with self._lock:
            self._prune_presence(now)
            self._presence[key] = presence

    def _prune_presence(self, now: int) -> None:
        cutoff = now - self.presence_ttl_seconds
        expired = [key for key, item in self._presence.items() if item.seen_at < cutoff]
        for key in expired:
            self._presence.pop(key, None)

    def record_event(
        self,
        *,
        kind: str,
        name: str,
        route: str,
        auth_state: str,
        outcome: str | None = None,
        viewport: str | None = None,
        export_format: str | None = None,
        status_code: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        now = int(self._clock())
        event: dict[str, Any] = {
            "ts": now,
            "kind": kind,
            "name": name,
            "route": route,
            "auth_state": auth_state,
        }
        optional = {
            "outcome": outcome,
            "viewport": viewport,
            "export_format": export_format,
            "status_code": status_code,
        }
        event.update({key: value for key, value in optional.items() if value is not None})
        encoded = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
        try:
            with self._lock:
                self._prepare_storage()
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(encoded + "\n")
                self._compact_if_due(now)
        except OSError:
            # Observability is diagnostic and must never break a product action.
            return

    def record_backend_error(self, *, route: str, status_code: int) -> None:
        self.record_event(
            kind="backend_error",
            name="http_5xx",
            route=route,
            auth_state="unknown",
            status_code=status_code,
        )

    def _read_retained(self, now: int) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        cutoff = now - (self.retention_hours * 3_600)
        retained: list[dict[str, Any]] = []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and isinstance(event.get("ts"), int) and event["ts"] >= cutoff:
                retained.append(event)
        return retained[-_MAX_RECORDS:]

    def _compact_if_due(self, now: int) -> None:
        if now - self._last_compacted_at < _COMPACT_INTERVAL_SECONDS:
            return
        retained = self._read_retained(now)
        temporary = self._path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for event in retained:
                handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(self._path)
        self._last_compacted_at = now

    def snapshot(self) -> dict[str, Any]:
        now = int(self._clock())
        with self._lock:
            self._prune_presence(now)
            events = self._read_retained(now) if self.enabled else []
            presence = list(self._presence.values())
        return {
            "generated_at": now,
            "retention_hours": self.retention_hours,
            "active": self._active_snapshot(presence),
            "totals": dict(Counter(str(item["kind"]) for item in events)),
            "actions": self._action_counts(events),
            "errors": self._error_counts(events),
            "recent": list(reversed(events[-_MAX_RECENT:])),
        }

    def _active_snapshot(self, presence: list[Presence]) -> dict[str, int]:
        authenticated = len({
            item.account_key
            for item in presence
            if item.auth_state == "authenticated" and item.account_key is not None
        })
        guests = sum(item.auth_state == "guest" for item in presence)
        return {
            "authenticated_accounts": authenticated,
            "guest_browser_sessions": guests,
            "estimated_total": authenticated + guests,
            "window_seconds": self.presence_ttl_seconds,
        }

    @staticmethod
    def _action_counts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = Counter(
            (item["name"], item.get("outcome", "observed"), item.get("export_format"))
            for item in events
            if item.get("kind") == "action"
        )
        return [
            {"name": name, "outcome": outcome, "export_format": export_format, "count": count}
            for (name, outcome, export_format), count in keys.most_common()
        ]

    @staticmethod
    def _error_counts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        errors = [item for item in events if str(item.get("kind", "")).endswith("error")]
        keys = Counter(
            (item["kind"], item["name"], item["route"], item.get("status_code"))
            for item in errors
        )
        return [
            {
                "kind": kind,
                "name": name,
                "route": route,
                "status_code": status_code,
                "count": count,
            }
            for (kind, name, route, status_code), count in keys.most_common()
        ]


def route_bucket(path: str) -> str:
    """Reduce a request path to a fixed product surface without identifiers."""
    if path.startswith("/auth"):
        return "auth"
    if path.startswith("/billing"):
        return "billing"
    if path.startswith("/feedback"):
        return "feedback"
    if path.startswith("/observability"):
        return "observability"
    if path.startswith("/videos"):
        return "videos"
    if path.startswith("/history"):
        return "history"
    if path.startswith("/static"):
        return "media"
    if path == "/health":
        return "health"
    return "other"
