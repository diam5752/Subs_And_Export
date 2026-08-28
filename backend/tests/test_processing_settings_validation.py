"""Boundary coverage for the public processing-settings builder."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api.endpoints import settings as settings_endpoint


def _valid_arguments() -> dict[str, object]:
    return {
        "transcribe_tier": "standard",
        "transcribe_provider": "groq",
        "openai_model": "",
        "video_quality": "balanced",
        "video_resolution": "720x1280",
        "context_prompt": "",
        "subtitle_position": 16,
        "max_subtitle_lines": 2,
        "subtitle_color": None,
        "shadow_strength": 4,
        "highlight_style": "karaoke",
        "subtitle_size": 100,
        "karaoke_enabled": True,
        "watermark_enabled": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("context_prompt", "x" * 5_001, "Context prompt too long"),
        ("transcribe_tier", "x" * 51, "Model name too long"),
        ("video_quality", "x" * 51, "Video quality string too long"),
        ("transcribe_provider", "x" * 51, "Provider name too long"),
        ("openai_model", "x" * 51, "OpenAI model name too long"),
        ("video_resolution", "x" * 51, "Resolution string too long"),
        ("highlight_style", "x" * 21, "Highlight style too long"),
    ],
)
def test_processing_settings_rejects_oversized_request_fields(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setattr(settings_endpoint.settings, "mock_external_services", False)
    arguments = _valid_arguments()
    arguments[field] = value

    with pytest.raises(HTTPException, match=message):
        settings_endpoint.build_processing_settings(**arguments)  # type: ignore[arg-type]


def test_processing_settings_rejects_tier_provider_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_endpoint.settings, "mock_external_services", False)
    arguments = _valid_arguments()
    arguments["transcribe_provider"] = "elevenlabs"

    with pytest.raises(HTTPException, match="does not match selected tier"):
        settings_endpoint.build_processing_settings(**arguments)  # type: ignore[arg-type]


def test_processing_settings_rejects_openai_model_for_another_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_endpoint.settings, "mock_external_services", False)
    arguments = _valid_arguments()
    arguments["openai_model"] = "whisper-1"

    with pytest.raises(HTTPException, match="requires transcribe_provider=openai"):
        settings_endpoint.build_processing_settings(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("subtitle_color", "message"),
    [
        ("&H" + ("A" * 30), "Subtitle color too long"),
        ("yellow", "Invalid subtitle color format"),
    ],
)
def test_processing_settings_rejects_unsafe_subtitle_colors(
    monkeypatch: pytest.MonkeyPatch,
    subtitle_color: str,
    message: str,
) -> None:
    monkeypatch.setattr(settings_endpoint.settings, "mock_external_services", False)
    arguments = _valid_arguments()
    arguments["subtitle_color"] = subtitle_color

    with pytest.raises(HTTPException, match=message):
        settings_endpoint.build_processing_settings(**arguments)  # type: ignore[arg-type]


def test_processing_settings_accepts_a_valid_ass_color_and_provider_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_endpoint.settings, "mock_external_services", False)
    arguments = _valid_arguments()
    arguments["transcribe_provider"] = ""
    arguments["subtitle_color"] = "&H00FFFF00"

    result = settings_endpoint.build_processing_settings(**arguments)  # type: ignore[arg-type]

    assert result.transcribe_provider == settings_endpoint.settings.transcribe_tier_provider["standard"]
    assert result.subtitle_color == "&H00FFFF00"
