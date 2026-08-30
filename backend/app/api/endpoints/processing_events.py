"""Best-effort event recording for background processing."""

import logging
from typing import Any

from ...core.auth import User
from ...services.history import HistoryStore


def record_event_safe(
    history_store: HistoryStore | None,
    user: User | None,
    kind: str,
    summary: str,
    data: dict[str, Any],
    *,
    logger: logging.Logger,
) -> None:
    """Record history without allowing observability to fail processing."""
    if not history_store or not user:
        return
    try:
        history_store.record_event(user, kind, summary, data)
    except Exception as exc:
        logger.warning("Failed to record history event %s: %s", kind, exc)
