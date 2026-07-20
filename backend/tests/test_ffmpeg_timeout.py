import pytest
import subprocess
import time
from unittest.mock import MagicMock
from pathlib import Path
from backend.app.services import ffmpeg_utils

def test_run_ffmpeg_with_subs_timeout(monkeypatch, tmp_path):
    """Test that run_ffmpeg_with_subs raises TimeoutError when the process exceeds the timeout."""

    # Mock subprocess.Popen to simulate a hanging process
    mock_process = MagicMock()
    mock_process.stderr.readline.return_value = ""  # Simulate no output
    mock_process.poll.return_value = None  # Simulate process still running
    mock_process.returncode = None

    # Simulate a process that hangs for a bit
    start_time = time.monotonic()

    def side_effect(*args, **kwargs):
        return mock_process

    monkeypatch.setattr(subprocess, "Popen", side_effect)

    # We need to mock select.select to simulate blocking or waiting
    # In the real code, select.select returns when there is data or timeout
    # Here we want to simulate that it returns nothing (timeout) so the loop continues
    # and eventually hits our timeout check
    monkeypatch.setattr(ffmpeg_utils.select, "select", lambda *args: ([], [], []))

    input_path = tmp_path / "input.mp4"
    ass_path = tmp_path / "subs.ass"
    output_path = tmp_path / "output.mp4"

    # Create dummy files
    input_path.touch()
    ass_path.touch()

    # Call with a short timeout
    with pytest.raises(TimeoutError) as excinfo:
        ffmpeg_utils.run_ffmpeg_with_subs(
            input_path,
            ass_path,
            output_path,
            video_crf=23,
            video_preset="fast",
            audio_bitrate="128k",
            audio_copy=False,
            timeout=0.1,  # Short timeout for testing
        )

    assert "FFmpeg process timed out" in str(excinfo.value)

    # Verify process was killed
    mock_process.kill.assert_called()
