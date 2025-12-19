"""Error handling utilities for security and privacy."""

import logging
import re
from typing import Union, Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# Regex to detect internal paths (Unix/Linux focus for container env)
_PATH_PATTERN = re.compile(r"(\/(?:app|home|var|tmp|usr|etc|opt)\/[\w\-\.\/]+)")

def sanitize_message(msg: str) -> str:
    """
    Sanitize string messages to prevent leaking internal details.
    """
    if _PATH_PATTERN.search(msg):
        return _PATH_PATTERN.sub("[INTERNAL_PATH]", msg)
    return msg

def create_error_response(status_code: int, message: str, error_code: str = None) -> JSONResponse:
    content = {"detail": message}
    if error_code:
        content["code"] = error_code
    return JSONResponse(status_code=status_code, content=content)

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Handle explicit HTTP exceptions (e.g. 404, 403).
    """
    return create_error_response(exc.status_code, sanitize_message(str(exc.detail)))

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle Pydantic validation errors.
    """
    errors = exc.errors()
    
    # Specific logic ported from main.py for batch delete limit
    if request.url.path.endswith("/videos/jobs/batch-delete"):
         for error in errors:
            loc = error.get("loc", ())
            ctx = error.get("ctx", {})
            if (
                error.get("type") == "too_long"
                and isinstance(loc, tuple)
                and loc[-1] == "job_ids"
                and ctx.get("max_length") == 50
            ):
                return create_error_response(status.HTTP_400_BAD_REQUEST, "Cannot delete more than 50 jobs at once")

    sanitized_errors = []
    for err in errors:
        loc = ".".join([str(x) for x in err.get("loc", [])])
        msg = err.get("msg", "Invalid input")
        sanitized_errors.append(f"{loc}: {msg}")
    
    error_msg = "; ".join(sanitized_errors)
    return create_error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Validation Error: {sanitize_message(error_msg)}")

async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    """
    Handle database errors. Log the full error, return generic message.
    """
    logger.exception("Database error occurred", extra={"path": request.url.path})
    return create_error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, 
        "A database error occurred. Please try again later.",
        "DB_ERROR"
    )

async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions.
    """
    logger.exception("Unhandled exception", extra={"path": request.url.path})
    return create_error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An internal server error occurred.",
        "INTERNAL_ERROR"
    )

def register_exception_handlers(app: FastAPI):
    """
    Registrar for all exception handlers.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
