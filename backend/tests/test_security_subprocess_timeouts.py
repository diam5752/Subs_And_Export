import subprocess
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from backend.app.services.ffmpeg_utils import probe_media
from backend.app.services.subtitles import get_video_duration

def test_probe_media_timeout():
    """Verify probe_media enforces a timeout on subprocess.run."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "{}"
        mock_run.return_value.returncode = 0

        probe_media(Path("test.mp4"))

        # Check that timeout arg was passed
        kwargs = mock_run.call_args[1]
        assert "timeout" in kwargs, "subprocess.run in probe_media must have a timeout"
        assert kwargs["timeout"] >= 10, "timeout should be at least 10 seconds"

def test_get_video_duration_timeout():
    """Verify get_video_duration enforces a timeout on subprocess.run."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "10.5"
        mock_run.return_value.returncode = 0

        get_video_duration(Path("test.mp4"))

        # Check that timeout arg was passed
        kwargs = mock_run.call_args[1]
        assert "timeout" in kwargs, "subprocess.run in get_video_duration must have a timeout"
        assert kwargs["timeout"] >= 10, "timeout should be at least 10 seconds"
