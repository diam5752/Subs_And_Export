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
from backend.app.services.settings_utils import parse_legacy_position
from backend.app.services.styles import SubtitleStyle


def test_validation_helpers_accept_valid_inputs() -> None:
    assert validate_transcribe_provider(" LOCAL ") == "local"
    assert validate_transcribe_tier(" PRO ") == "pro"
    assert validate_model_name(" whisper-large-v3 ", allow_empty=False, field_name="model") == "whisper-large-v3"
    assert validate_video_quality(" HIGH QUALITY ") == "high quality"
    assert validate_subtitle_position(12) == 12
    assert validate_max_subtitle_lines(4) == 4
    assert validate_shadow_strength(3) == 3
    assert validate_subtitle_size(120) == 120
    assert validate_highlight_style(" ACTIVE ") == "active"
    assert validate_upload_content_type("") == "application/octet-stream"


@pytest.mark.parametrize(
    ("func", "value", "detail"),
    [
        (validate_transcribe_provider, "weird", "Invalid transcribe provider"),
        (validate_transcribe_tier, "ultra", "Invalid transcribe tier"),
        (validate_video_quality, "tiny", "Invalid video quality"),
        (validate_subtitle_position, 4, "subtitle_position out of range (5-35)"),
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


def test_parse_legacy_position_and_style_renderer_kwargs() -> None:
    assert parse_legacy_position(None) == 16
    assert parse_legacy_position(99) == 50
    assert parse_legacy_position("top") == 32
    assert parse_legacy_position("unknown") == 16

    pop_style = SubtitleStyle(highlight_style="pop", max_lines=2)
    assert pop_style.to_renderer_kwargs(1080, 1920) == {
        "font": pop_style.font_family,
        "font_size": pop_style.font_size,
        "primary_color": pop_style.primary_color,
        "stroke_color": pop_style.stroke_color,
        "stroke_width": pop_style.stroke_width,
        "width": 1080,
        "height": 1920,
        "margin_bottom": pop_style.margin_bottom,
    }

    karaoke_style = SubtitleStyle(highlight_style="karaoke", max_lines=2)
    karaoke_kwargs = karaoke_style.to_renderer_kwargs(1080, 1920)
    assert karaoke_kwargs["secondary_color"] == karaoke_style.secondary_color
    assert karaoke_kwargs["margin_x"] == karaoke_style.margin_x
    assert karaoke_kwargs["max_lines"] == 2
