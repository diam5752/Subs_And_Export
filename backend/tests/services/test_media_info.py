import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import subtitles


def test_get_media_info_success(monkeypatch):
    """Test get_media_info returns correct duration and audio codec."""
    mock_json_output = {
        "format": {
            "duration": "123.456"
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264"
            },
            {
                "codec_type": "audio",
                "codec_name": "aac"
            }
        ]
    }

    class MockResult:
        stdout = json.dumps(mock_json_output)
        returncode = 0

    monkeypatch.setattr(subtitles.subprocess, "run", lambda *args, **kwargs: MockResult())

    info = subtitles.get_media_info(Path("dummy.mp4"))
    assert info.duration == 123.456
    assert info.audio_codec == "aac"


def test_get_media_info_no_audio(monkeypatch):
    """Test get_media_info handles missing audio stream."""
    mock_json_output = {
        "format": {
            "duration": "10.0"
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264"
            }
        ]
    }

    class MockResult:
        stdout = json.dumps(mock_json_output)
        returncode = 0

    monkeypatch.setattr(subtitles.subprocess, "run", lambda *args, **kwargs: MockResult())

    info = subtitles.get_media_info(Path("dummy.mp4"))
    assert info.duration == 10.0
    assert info.audio_codec is None


def test_get_media_info_error(monkeypatch):
    """Test get_media_info raises error on subprocess failure."""
    def mock_run(*args, **kwargs):
        raise subtitles.subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(subtitles.subprocess, "run", mock_run)

    with pytest.raises(subtitles.subprocess.CalledProcessError):
        subtitles.get_media_info(Path("dummy.mp4"))
