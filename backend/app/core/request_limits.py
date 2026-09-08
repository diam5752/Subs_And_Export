"""Bound automatic body parsing before FastAPI resolves dependencies."""

from __future__ import annotations

import re

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_BODY_LIMIT = 1_000_000
TRANSCRIPTION_BODY_LIMIT = 8 * 1024 * 1024
_TRANSCRIPTION_PATH = re.compile(r"/videos/jobs/[^/]+/transcription")
_MANUALLY_BOUNDED_PATHS = {
    "/videos/process-stream",
    "/videos/mobile-transcriptions",
    "/billing/webhook",
}
_SMALL_BODY_LIMITS = {"/feedback": 16_000, "/observability/events": 4_000}


def request_body_limit(scope: Scope) -> int | None:
    path = scope.get("path", "").rstrip("/")
    method = scope.get("method", "")
    # These routes authenticate/verify and count their own actual stream bytes.
    # Do not buffer media or change their upload/refund error contracts here.
    if method == "POST" and path in _MANUALLY_BOUNDED_PATHS:
        return None
    if method == "PUT" and _TRANSCRIPTION_PATH.fullmatch(path):
        return TRANSCRIPTION_BODY_LIMIT
    return _SMALL_BODY_LIMITS.get(path, DEFAULT_BODY_LIMIT)


def _declared_body_too_large(scope: Scope, limit: int) -> bool:
    ceiling = str(limit).encode("ascii")
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        # Compare decimal digits without constructing an unbounded integer.
        digits = value.strip().lstrip(b"0") or b"0"
        if digits.isdigit() and (len(digits), digits) > (len(ceiling), ceiling):
            return True
    return False


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = request_body_limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        detail = "Request body is too large"
        if _declared_body_too_large(scope, limit):
            await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Raised inside the route's parser; ExceptionMiddleware
                    # returns 413 without letting the offending chunk reach it.
                    raise HTTPException(status_code=413, detail=detail)
            return message

        await self.app(scope, limited_receive, send)
