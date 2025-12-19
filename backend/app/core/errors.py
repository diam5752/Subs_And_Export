"""Error handling utilities for security and privacy."""

import logging
import re
import subprocess
from typing import Union

logger = logging.getLogger(__name__)

# Regex to detect internal paths (Unix/Linux focus for container env)
# Matches paths starting with /app, /home, /var, /tmp, /usr, /etc
_PATH_PATTERN = re.compile(r"(\/(?:app|home|var|tmp|usr|etc|opt)\/[\w\-\.\/]+)")


def sanitize_error(exc: Union[Exception, str]) -> str:
    """
    Sanitize exception messages to prevent leaking internal details.

    - Strips internal file paths.
    - Masks subprocess commands.
    - Allows safe exceptions (ValueError, PermissionError) to pass through with sanitized messages.
    - Hides unexpected internal errors with a generic message.
    """
    if isinstance(exc, str):
        msg = exc
        # Sanitize paths in string
        if _PATH_PATTERN.search(msg):
            msg = _PATH_PATTERN.sub("[INTERNAL_PATH]", msg)
        return msg

    # Handle subprocess errors specifically (they leak command args)
    if isinstance(exc, subprocess.CalledProcessError):
        logger.error(f"Subprocess failed: {exc}")
        return f"Processing command failed with exit code {exc.returncode}"

    msg = str(exc)

    # Sanitize paths
    if _PATH_PATTERN.search(msg):
        msg = _PATH_PATTERN.sub("[INTERNAL_PATH]", msg)

    # Filter by type
    if isinstance(exc, (ValueError, PermissionError, InterruptedError)):
        return msg

    # Default generic error for unknown types
    logger.exception("Internal error caught: %s", exc)
    return "An internal error occurred"
