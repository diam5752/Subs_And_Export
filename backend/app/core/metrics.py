"""Lightweight metrics/logging helpers for pipeline timing."""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from backend.app.core.config import settings


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

    return settings.is_dev

def _resolve_log_path() -> Path:
    explicit = os.getenv("PIPELINE_LOG_PATH")
    if explicit:
        return Path(explicit).resolve()
    return (settings.project_root / "logs" / "pipeline_metrics.jsonl").resolve()


def log_pipeline_metrics(event: dict[str, Any]) -> None:
    """Append a JSONL metric row; never raises."""
    if not should_log_metrics():
        return

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "app_env": settings.app_env.value,
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


@contextmanager
def measure_time(
    timings_dict: dict[str, float], key: str
) -> Generator[None, None, None]:
    """
    Context manager to measure execution time and store it in a dictionary.

    Usage:
        with measure_time(timings, "my_step_s"):
            do_work()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        timings_dict[key] = time.perf_counter() - start
