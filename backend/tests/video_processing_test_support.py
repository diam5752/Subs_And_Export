"""Shared fixtures for split video-processing test modules."""

import pytest

from backend.app.services import video_processing


@pytest.fixture(autouse=True)
def default_cloud_keys_for_video_processing_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        video_processing.provider_clients,
        "resolve_groq_api_key",
        lambda: "test-groq-key",
    )
    monkeypatch.setattr(
        video_processing.provider_clients,
        "resolve_openai_api_key",
        lambda explicit=None: explicit or "test-openai-key",
    )
