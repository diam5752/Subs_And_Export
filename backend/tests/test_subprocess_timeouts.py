from pathlib import Path
from unittest.mock import patch

from backend.app.services import ffmpeg_utils, subtitles

# Mock the setup_test_database fixture to avoid DB requirement
# We need to match the name in conftest.py to override it, or just not fail.
# Since conftest.py handles failures, we might be fine.
# But let's try to patch subprocess.run locally just for this file if possible? No.

def test_probe_media_timeout():
    """Verify probe_media passes a timeout to subprocess.run."""
    with patch("subprocess.run") as mock_run:
        # Mock successful return
        mock_run.return_value.stdout = "{}"
        mock_run.return_value.returncode = 0

        # Call the function
        try:
            ffmpeg_utils.probe_media(Path("dummy.mp4"))
        except Exception:
            # We don't care if it fails due to parsing, we care about the call
            pass

        # Assert timeout is passed
        args, kwargs = mock_run.call_args
        assert "timeout" in kwargs, "timeout argument missing in probe_media call"
        assert kwargs["timeout"] >= 10, "timeout value is too low"

def test_get_video_duration_timeout():
    """Verify get_video_duration passes a timeout to subprocess.run."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "10.5"
        mock_run.return_value.returncode = 0

        subtitles.get_video_duration(Path("dummy.mp4"))

        args, kwargs = mock_run.call_args
        assert "timeout" in kwargs, "timeout argument missing in get_video_duration call"
        assert kwargs["timeout"] >= 10, "timeout value is too low"
