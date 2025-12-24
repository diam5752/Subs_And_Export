from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from unittest.mock import patch, Mock

from backend.app.services.ffmpeg_utils import probe_media

logger = logging.getLogger(__name__)

class TestFFmpegTimeouts:
    """Test verification of timeout enforcement in FFmpeg calls."""

    @patch("subprocess.run")
    def test_probe_media_enforces_timeout(self, mock_run):
        """Verify probe_media uses a timeout."""
        # Setup mock to behave like a successful run
        mock_run.return_value = Mock(
            stdout='{"format": {"duration": "10.0"}}',
            stderr="",
            returncode=0
        )

        input_path = Path("fake_video.mp4")
        probe_media(input_path)

        # Verify timeout argument was passed
        args, kwargs = mock_run.call_args
        assert "timeout" in kwargs, "subprocess.run missing timeout argument"
        assert kwargs["timeout"] >= 10, "Timeout should be reasonable (>= 10s)"
