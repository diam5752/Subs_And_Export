"""Error handling utilities."""

import logging
import subprocess

logger = logging.getLogger(__name__)

# Exceptions that are safe to show to the user
SAFE_EXCEPTIONS = (
    ValueError,
    PermissionError,
    subprocess.CalledProcessError,  # Handled specially
)

def sanitize_error(e: Exception, generic_message: str = "An internal error occurred") -> str:
    """
    Return a safe error message for public display.
    Logs the full error if it's considered unsafe.
    """
    if isinstance(e, ValueError):
        # ValueErrors often contain validation messages which are safe
        return str(e)

    if isinstance(e, PermissionError):
        # "Access denied" etc.
        return str(e)

    if isinstance(e, subprocess.CalledProcessError):
        # We want to show that processing failed, but avoid leaking command args or paths
        # returncode is safe.
        # stderr might contain paths.
        # We can return a sanitized version.
        msg = f"Process failed with exit code {e.returncode}."
        # If we have stderr, check if it contains common safe errors
        if e.stderr:
            # Very basic check for "Invalid data found" or similar which is helpful
            if "Invalid data found" in e.stderr:
                return f"{msg} Invalid video data."
            if "does not contain any stream" in e.stderr:
                return f"{msg} No video streams found."
        return msg

    # Log the full error for debugging
    logger.error(f"Unsafe error caught: {type(e).__name__}: {e}", exc_info=True)

    return generic_message
