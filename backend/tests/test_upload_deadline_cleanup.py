"""Run a trickled upload through the real authenticated ASGI route."""

import base64
import json
from unittest.mock import MagicMock

import anyio

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore


def test_total_deadline_refunds_and_releases_the_real_upload(client, funded_user_auth_headers, monkeypatch) -> None:
    from backend.app.api.endpoints import videos

    user_id = client.get("/auth/me", headers=funded_user_auth_headers).json()["id"]
    points = PointsStore(Database())
    balance = points.get_balance(user_id)
    monkeypatch.setattr(settings, "upload_inactivity_timeout_seconds", 1)
    monkeypatch.setattr(settings, "upload_total_timeout_seconds", 0.04)
    dispatch = MagicMock(side_effect=AssertionError("A partial upload must not be processed"))
    monkeypatch.setattr(videos, "_queue_saved_upload", dispatch)
    metadata = base64.b64encode(json.dumps({"filename": "clip.mp4", "authorized_credits": 30}).encode()).decode()
    headers = {
        **funded_user_auth_headers,
        "Host": "testserver",
        "Content-Type": "video/mp4",
        "Content-Length": "100",
        "X-Gsubs-Upload-Metadata": metadata,
    }
    sent = []
    reads = 0

    async def run() -> None:
        async def receive():
            nonlocal reads
            await anyio.sleep(0.005)
            reads += 1
            return {"type": "http.request", "body": b"x", "more_body": reads < 100}

        async def send(message):
            sent.append(message)

        await client.app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/videos/process-stream",
                "raw_path": b"/videos/process-stream",
                "query_string": b"",
                "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )

    assert client.portal is not None
    client.portal.call(run)
    assert sent[0]["status"] == 408
    assert 0 < reads < 100
    assert points.get_balance(user_id) == balance
    assert JobStore(Database()).list_jobs_for_user(user_id) == []
    dispatch.assert_not_called()
    _, uploads, artifacts = videos.data_roots()
    assert list(uploads.iterdir()) == []
    assert list(artifacts.iterdir()) == []
