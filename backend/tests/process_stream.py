"""Test helpers for the authenticated raw video upload contract."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response


def post_process_stream(
    client: TestClient,
    auth_headers: Mapping[str, str],
    *,
    filename: str = "clip.mp4",
    content: bytes = b"video",
    content_type: str = "video/mp4",
    metadata: Mapping[str, Any] | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> Response:
    """Post one raw upload using the browser-facing streaming metadata contract."""
    payload: dict[str, Any] = {
        "filename": filename,
        "authorized_credits": 100,
    }
    if metadata is not None:
        payload.update(metadata)
    encoded_metadata = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    ).decode("ascii")
    headers = {
        **auth_headers,
        "Content-Type": content_type,
        "X-Gsubs-Upload-Metadata": encoded_metadata,
    }
    if extra_headers is not None:
        headers.update(extra_headers)
    return client.post(
        "/videos/process-stream",
        headers=headers,
        content=content,
    )
