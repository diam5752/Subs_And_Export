"""Stripe webhook transport endpoint contracts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.api.endpoints.billing import stripe_webhook
from backend.app.services.billing import (
    BillingConflictError,
    BillingDisabledError,
    BillingProviderError,
    BillingValidationError,
    WebhookResult,
)


class _RecordingBillingService:
    def __init__(self) -> None:
        self.calls = 0
        self.payload: bytes | None = None
        self.signature: str | None = None

    def verify_and_process_webhook(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> WebhookResult:
        self.calls += 1
        self.payload = payload
        self.signature = signature
        return WebhookResult(
            event_id="evt_streamed",
            event_type="customer.updated",
            status="ignored",
        )


def _streaming_request(
    chunks: list[bytes],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[Request, dict[str, int]]:
    state = {"receive_calls": 0}
    pending = list(chunks)

    async def receive() -> dict[str, Any]:
        state["receive_calls"] += 1
        if not pending:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        body = pending.pop(0)
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(pending),
        }

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/billing/webhook",
        "raw_path": b"/billing/webhook",
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 443),
    }
    return Request(scope, receive), state


def test_webhook_stream_rejects_chunked_payload_immediately_before_service() -> None:
    request, stream_state = _streaming_request(
        [
            b"a" * 600_000,
            b"b" * 400_000,
            b"c",
            b"must-not-be-read",
        ],
    )
    service = _RecordingBillingService()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=service,  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == 413
    assert stream_state["receive_calls"] == 3
    assert service.calls == 0


@pytest.mark.parametrize(
    ("content_length", "expected_status", "expected_detail"),
    [
        (b"1000001", 413, "Webhook payload is too large"),
        (b"not-an-integer", 400, "Invalid Content-Length"),
        (b"", 400, "Invalid Content-Length"),
        (b"-1", 400, "Invalid Content-Length"),
        (b"+1", 400, "Invalid Content-Length"),
        (b" 1", 400, "Invalid Content-Length"),
    ],
)
def test_webhook_rejects_unsafe_content_length_before_reading_stream(
    content_length: bytes,
    expected_status: int,
    expected_detail: str,
) -> None:
    request, stream_state = _streaming_request(
        [b"must-not-be-read"],
        headers=[(b"content-length", content_length)],
    )
    service = _RecordingBillingService()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=service,  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert stream_state["receive_calls"] == 0
    assert service.calls == 0


def test_webhook_stream_preserves_empty_body_rejection() -> None:
    request, _ = _streaming_request([b""])
    service = _RecordingBillingService()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=service,  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == 400
    assert service.calls == 0


def test_webhook_stream_passes_valid_payload_once() -> None:
    request, _ = _streaming_request(
        [b"", b'{"id":', b'"evt_streamed"}'],
        headers=[(b"content-length", b"21")],
    )
    service = _RecordingBillingService()

    response = asyncio.run(
        stripe_webhook(
            request,
            stripe_signature="test-signature",
            billing_service=service,  # type: ignore[arg-type]
        ),
    )

    assert response == {
        "event_id": "evt_streamed",
        "event_type": "customer.updated",
        "status": "ignored",
    }
    assert service.calls == 1
    assert service.payload == b'{"id":"evt_streamed"}'
    assert service.signature == "test-signature"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (BillingDisabledError("disabled"), 503),
        (BillingConflictError("conflict"), 409),
        (BillingValidationError("invalid"), 400),
        (BillingProviderError("provider"), 502),
        (RuntimeError("secret internal detail"), 500),
    ],
)
def test_webhook_maps_billing_failures_without_leaking_unknown_errors(
    error: Exception,
    expected_status: int,
) -> None:
    class _FailingBillingService(_RecordingBillingService):
        def verify_and_process_webhook(
            self,
            *,
            payload: bytes,
            signature: str,
        ) -> WebhookResult:
            raise error

    request, _ = _streaming_request([b"{}"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=_FailingBillingService(),  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == ("Billing operation failed" if expected_status == 500 else str(error))
    assert "secret internal detail" not in str(exc_info.value.detail)
