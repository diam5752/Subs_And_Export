import json
import logging
import sys
from datetime import datetime
from typing import Any

# Configure logging levels
LOG_LEVEL = logging.DEBUG  # Can be configurable via env var

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
    logging.getLogger("uvicorn.access").disabled = True # Disable default access logs to rely on our own middleware or just reduce noise
    
    return logger
