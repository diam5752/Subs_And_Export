from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.api.endpoints.export_routes import ExportRequest
from backend.app.api.endpoints.validation import (
    validate_highlight_style,
    validate_max_subtitle_lines,
    validate_model_name,
    validate_shadow_strength,
    validate_subtitle_position,
    validate_subtitle_size,
    validate_transcribe_provider,
    validate_transcribe_tier,
    validate_upload_content_type,
    validate_video_quality,
)
from backend.app.services.settings_utils import normalize_subtitle_position
from backend.app.services.styles import SubtitleStyle


def test_validation_helpers_accept_valid_inputs() -> None:
    assert validate_transcribe_provider(" LOCAL ") == "local"
    assert validate_transcribe_provider(" ELEVENLABS ") == "elevenlabs"
    assert validate_transcribe_tier(" PRO ") == "pro"
    assert validate_model_name(" whisper-large-v3 ", allow_empty=False, field_name="model") == "whisper-large-v3"
    assert validate_video_quality(" HIGH QUALITY ") == "high quality"
    assert validate_subtitle_position(12) == 12
    assert validate_max_subtitle_lines(4) == 4
    assert validate_shadow_strength(3) == 3
    assert validate_subtitle_size(120) == 120
    assert validate_highlight_style(" ACTIVE-GRAPHICS ") == "active-graphics"
    assert validate_upload_content_type("") == "application/octet-stream"


@pytest.mark.parametrize(
    ("func", "value", "detail"),
    [
        (validate_transcribe_provider, "weird", "Invalid transcribe provider"),
        (validate_transcribe_tier, "ultra", "Invalid transcribe tier"),
        (validate_video_quality, "tiny", "Invalid video quality"),
        (validate_subtitle_position, 4, "subtitle_position out of range (5-95)"),
        (validate_subtitle_position, 96, "subtitle_position out of range (5-95)"),
        (validate_max_subtitle_lines, 5, "max_subtitle_lines out of range (0-4)"),
        (validate_shadow_strength, 11, "shadow_strength out of range (0-10)"),
        (validate_subtitle_size, 49, "subtitle_size out of range (50-150)"),
        (validate_highlight_style, "flashy", "Invalid highlight style"),
        (validate_upload_content_type, "text/plain", "Invalid content type"),
    ],
)
def test_validation_helpers_reject_invalid_inputs(func, value, detail: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        func(value)
    assert exc_info.value.detail == detail


def test_validate_model_name_rejects_empty_and_unsafe_values() -> None:
    with pytest.raises(HTTPException) as empty_exc:
        validate_model_name("   ", allow_empty=False, field_name="model")
    assert empty_exc.value.detail == "model is required"

    assert validate_model_name("   ", allow_empty=True, field_name="model") is None

    for unsafe_value in ("../secret", "/abs", "\\network", "bad:name", "bad\\model", "bad space"):
        with pytest.raises(HTTPException):
            validate_model_name(unsafe_value, allow_empty=False, field_name="model")


def test_export_request_validates_subtitle_color() -> None:
    assert ExportRequest(resolution="srt").resolution == "srt"
    assert ExportRequest(resolution="vtt").resolution == "vtt"
    assert ExportRequest(resolution="txt").resolution == "txt"
    assert ExportRequest(resolution="1080x1920", subtitle_color=None).subtitle_color is None
    assert ExportRequest(resolution="1080x1920", subtitle_color="&H00FFFFFF").subtitle_color == "&H00FFFFFF"

    with pytest.raises(ValidationError):
        ExportRequest(resolution="1080x1920", subtitle_color="#FFFFFF")


def test_normalize_subtitle_position_and_style_contract() -> None:
    assert normalize_subtitle_position(None) == 16
    assert normalize_subtitle_position(99) == 95
    assert normalize_subtitle_position(95) == 95
    assert normalize_subtitle_position(4) == 5
    assert normalize_subtitle_position("top") == 16
    assert normalize_subtitle_position(True) == 16

    style = SubtitleStyle(highlight_style="pop", max_lines=2)
    assert style.highlight_style == "pop"
    assert style.max_lines == 2
