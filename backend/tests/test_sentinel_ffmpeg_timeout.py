import pytest
import subprocess
import time
from unittest.mock import patch, MagicMock
from pathlib import Path
from backend.app.services.ffmpeg_utils import run_ffmpeg_with_subs
from backend.app.services.subtitles import extract_audio

def test_run_ffmpeg_timeout():
    """Verify run_ffmpeg_with_subs raises TimeoutError when process hangs."""

    # Mock subprocess.Popen to return a process that never finishes
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.stderr = MagicMock()
    # readline returns empty string only when file is closed,
    # but here we simulate a hang where select might not return anything or return data slowly.
    # To simulate hang, we make select.select return empty list (no data)

    # We need to mock select.select because run_ffmpeg_with_subs uses it
    with patch("subprocess.Popen", return_value=mock_process) as mock_popen, \
         patch("select.select", return_value=([], [], [])) as mock_select:

        start_time = time.monotonic()

        with pytest.raises(TimeoutError) as exc:
            run_ffmpeg_with_subs(
                Path("in.mp4"), Path("subs.ass"), Path("out.mp4"),
                video_crf=23, video_preset="fast", audio_bitrate="128k",
                audio_copy=False, timeout=0.1  # Very short timeout
            )

        duration = time.monotonic() - start_time
        assert "exceeded timeout" in str(exc.value)
        assert mock_process.kill.called, "Process should be killed on timeout"

def test_extract_audio_timeout():
    """Verify extract_audio raises TimeoutError when process hangs."""

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.stderr = MagicMock()

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen, \
         patch("select.select", return_value=([], [], [])) as mock_select:

        with pytest.raises(TimeoutError) as exc:
            extract_audio(
                Path("in.mp4"),
                timeout=0.1 # Very short timeout
            )

        assert "exceeded timeout" in str(exc.value)
        assert mock_process.kill.called, "Process should be killed on timeout"
