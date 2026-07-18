import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Configure logging levels
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)


class JSONFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None)
        if request_id is not None:
            log_record["request_id"] = request_id

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        data = getattr(record, "data", None)
        if data is not None:
            log_record["data"] = data

        return json.dumps(log_record, ensure_ascii=False, default=str)


def setup_logging() -> logging.Logger:
    """Configure and return the process-wide root logger."""
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    # Avoid duplicate output when application setup runs more than once.
    logger.handlers.clear()
    logger.addHandler(handler)

    # Specific tweaks for third-party libraries
    logging.getLogger("uvicorn.access").disabled = True

    # Silence noisy third-party libraries unless they are WARNING or higher
    for noisy_logger in ["torio", "torch", "faster_whisper", "stable_ts", "httpcore", "httpx"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    return logger
