"""Exercise the real parser boundary with small, bounded request streams."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import anyio
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.core import request_limits
from backend.app.core.request_limits import RequestBodyLimitMiddleware


def _application() -> tuple[FastAPI, MagicMock]:
    app = FastAPI()
    dependency = MagicMock()

    def authenticate() -> None:
        dependency()

    @app.post("/auth/register", dependencies=[Depends(authenticate)])
    def parsed_body(payload: dict) -> dict:
        return payload

    @app.put("/videos/jobs/{job_id}/transcription")
    def transcript(job_id: str, payload: dict) -> dict:
        return payload

    @app.post("/videos/process-stream")
    async def stream(request: Request) -> dict:
        return {"size": len(await request.body())}

    app.add_middleware(RequestBodyLimitMiddleware)
    return app, dependency


@pytest.mark.parametrize("declared", [b"33", b"00033", b"9" * 5_000])
def test_oversized_declared_body_never_reaches_parser(monkeypatch, declared: bytes) -> None:
    monkeypatch.setattr(request_limits, "DEFAULT_BODY_LIMIT", 32)
    app, dependency = _application()
    receive = MagicMock(side_effect=AssertionError("Body must not be read"))
    sent = []

    async def run() -> None:
        async def send(message) -> None:
            sent.append(message)

        await app(
            {"type": "http", "method": "POST", "path": "/auth/register", "headers": [(b"content-length", declared)]},
            receive,
            send,
        )

    anyio.run(run)
    assert sent[0]["status"] == 413
    receive.assert_not_called()
    dependency.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1"}])
def test_actual_stream_bytes_are_bounded_before_parsing(monkeypatch, headers) -> None:
    monkeypatch.setattr(request_limits, "DEFAULT_BODY_LIMIT", 32)
    app, dependency = _application()
    consumed = []

    def body():
        for chunk in (b'{"value":"', b"a" * 24, b"must-not-be-read"):
            consumed.append(chunk)
            yield chunk

    # TestClient coalesces iterable content, so use ASGI receive for chunk proof.
    sent = []
    iterator = iter(body())

    async def run() -> None:
        async def receive():
            return {"type": "http.request", "body": next(iterator), "more_body": True}

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "path": "/auth/register",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")]
                + [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            },
            receive,
            send,
        )

    anyio.run(run)
    assert sent[0]["status"] == 413
    assert len(consumed) == 2
    dependency.assert_not_called()


def test_valid_json_and_media_keep_their_separate_budgets(monkeypatch) -> None:
    monkeypatch.setattr(request_limits, "DEFAULT_BODY_LIMIT", 32)
    app, dependency = _application()
    with TestClient(app) as client:
        assert client.post("/auth/register", json={"value": "καλημέρα"}).status_code == 200
        assert client.put("/videos/jobs/example/transcription", json={"value": "a" * 40}).status_code == 200
        assert client.post("/videos/process-stream", content=b"a" * 40).json() == {"size": 40}
    dependency.assert_called_once()


def test_large_greek_transcript_fits_the_dedicated_budget() -> None:
    from backend.app.api.endpoints.job_routes import UpdateTranscriptionRequest

    payload = {"cues": [{"start": 0, "end": 1, "text": "Ελληνικοί υπότιτλοι σε κάθε λέξη. " * 10}] * 5_000}
    UpdateTranscriptionRequest.model_validate(payload)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert request_limits.DEFAULT_BODY_LIMIT < len(body) < request_limits.TRANSCRIPTION_BODY_LIMIT
    app, _ = _application()
    with TestClient(app) as client:
        assert (
            client.put(
                "/videos/jobs/example/transcription",
                content=body,
                headers={"Content-Type": "application/json"},
            ).status_code
            == 200
        )


@pytest.mark.parametrize("path", ["/videos/jobs/example/transcription", "/videos/jobs/example/transcription/"])
def test_transcript_budget_does_not_apply_to_other_methods(monkeypatch, path: str) -> None:
    monkeypatch.setattr(request_limits, "DEFAULT_BODY_LIMIT", 32)
    monkeypatch.setattr(request_limits, "TRANSCRIPTION_BODY_LIMIT", 64)
    app, _ = _application()
    with TestClient(app) as client:
        assert client.put(path, json={"value": "a" * 40}).status_code == 200
        assert client.post(path, content=b"a" * 40).status_code == 413
        assert client.put(path, content=b"a" * 65).status_code == 413


def test_actual_application_rejects_oversized_guest_request(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(request_limits, "DEFAULT_BODY_LIMIT", 32)
    response = client.post("/auth/register", content=b"a" * 33)
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large"
    assert response.headers["x-content-type-options"] == "nosniff"
    chunked = client.post(
        "/auth/register",
        content=b"a" * 33,
        headers={"Content-Length": "1", "Content-Type": "application/json"},
    )
    assert chunked.status_code == 413
