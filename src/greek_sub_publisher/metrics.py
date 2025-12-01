"""Lightweight metrics/logging helpers for pipeline timing."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config


def _env_bool(name: str) -> Optional[bool]:
    val = os.getenv(name)
    if val is None:
        return None
    val = val.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return None


def should_log_metrics() -> bool:
    """
    Decide whether to emit local metrics.
    - Explicit override via PIPELINE_LOGGING (1/0).
    - Otherwise, log in dev/local environments.
    - Skip during pytest unless explicitly enabled.
    """
    override = _env_bool("PIPELINE_LOGGING")
    if override is not None:
        return override

    if "PYTEST_CURRENT_TEST" in os.environ:
        return False

    env = os.getenv("APP_ENV") or os.getenv("ENV") or "dev"
    env = env.lower()
    return env in ("dev", "development", "local", "localhost")


def _resolve_log_path() -> Path:
    custom = os.getenv("PIPELINE_LOG_PATH")
    if custom:
        return Path(custom).expanduser().resolve()
    return (config.PROJECT_ROOT / "logs" / "pipeline_metrics.jsonl").resolve()


def log_pipeline_metrics(event: dict[str, Any]) -> None:
    """Append a JSONL metric row; never raises."""
    if not should_log_metrics():
        return

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "app_env": os.getenv("APP_ENV") or os.getenv("ENV") or "dev",
        **event,
    }

    path = _resolve_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False))
            fh.write("\n")
    except Exception:
        # Best-effort logging; swallow errors so pipeline never fails due to logging.
        return
