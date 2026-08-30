"""Bounded monitoring for line-oriented FFmpeg subprocesses."""

from __future__ import annotations

import re
import select as _select
import subprocess
import time
from collections.abc import Callable

select = _select


def _assert_before_deadline(
    *,
    now: float,
    deadline: float,
    timeout_message: str,
) -> None:
    if now >= deadline:
        raise TimeoutError(timeout_message)


def _check_cancellation(
    callback: Callable[[], None] | None,
    *,
    now: float,
    last_check: float,
) -> float:
    if callback is None or now - last_check <= 0.5:
        return last_check
    callback()
    return now


def _read_ready_line(
    process: subprocess.Popen[str],
    *,
    wait_seconds: float,
) -> str | None:
    if process.stderr is None:
        time.sleep(wait_seconds)
        return None
    reads, _, _ = select.select(
        [process.stderr],
        [],
        [],
        wait_seconds,
    )
    if not reads:
        return None
    return process.stderr.readline() or None


def _report_progress(
    line: str,
    *,
    pattern: re.Pattern[str],
    total_duration: float | None,
    callback: Callable[[float], None] | None,
) -> None:
    if callback is None or total_duration is None or total_duration <= 0:
        return
    match = pattern.search(line)
    if match is None:
        return
    hours, minutes, seconds = match.groups()
    current_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    callback(min(100.0, (current_seconds / total_duration) * 100.0))


def monitor_media_process(
    process: subprocess.Popen[str],
    *,
    deadline: float,
    timeout_message: str,
    progress_pattern: re.Pattern[str],
    check_cancelled: Callable[[], None] | None,
    progress_callback: Callable[[float], None] | None,
    total_duration: float | None,
    capture_line: Callable[[str], None] | None = None,
) -> None:
    """Monitor cancellation, timeout and progress until a process exits."""
    last_cancel_check = 0.0
    while True:
        now = time.monotonic()
        _assert_before_deadline(
            now=now,
            deadline=deadline,
            timeout_message=timeout_message,
        )
        last_cancel_check = _check_cancellation(
            check_cancelled,
            now=now,
            last_check=last_cancel_check,
        )
        line = _read_ready_line(
            process,
            wait_seconds=min(0.1, max(0.0, deadline - now)),
        )
        if line is None:
            pass
        else:
            if capture_line is not None:
                capture_line(line)
            _report_progress(
                line,
                pattern=progress_pattern,
                total_duration=total_duration,
                callback=progress_callback,
            )
        if process.poll() is not None:
            break

    _assert_before_deadline(
        now=time.monotonic(),
        deadline=deadline,
        timeout_message=timeout_message,
    )
