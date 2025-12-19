import json
import logging
import sys
from datetime import datetime
from typing import Any

import os

# Configure logging levels
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings after parsing the LogRecord.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        # Add specific fields if they exist
        if hasattr(record, "request_id"):
            log_record["request_id"] = record.request_id # type: ignore

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            # Or use a more structured stack trace if desired

        # Add extra fields passed via extra={}
        if hasattr(record, "data"):
             log_record["data"] = record.data # type: ignore

        return json.dumps(log_record)

def setup_logging():
    """
    Configures the root logger to use JSON formatting.
    """
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    
    # Remove existing handlers to avoid duplicates (e.g. from Uvicorn's default config)
    logger.handlers = []
    logger.addHandler(handler)

    # Specific tweaks for third-party libraries
    logging.getLogger("uvicorn.access").disabled = True
    
    # Silence noisy third-party libraries unless they are WARNING or higher
    for noisy_logger in ["torio", "torch", "faster_whisper", "stable_ts", "httpcore", "httpx"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    return logger
