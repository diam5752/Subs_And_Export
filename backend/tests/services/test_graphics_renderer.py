from pathlib import Path
from unittest.mock import MagicMock, patch, ANY
import json
import pytest
import numpy as np

from backend.app.services.graphics_renderer import render_active_word_video, _get_video_metadata
from backend.app.core import config

@pytest.fixture
def mock_subprocess():
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:

        # Mock probe response
        mock_run.return_value.stdout = json.dumps({
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "duration": "1.0" # Short duration for faster test
                },
                {
                    "codec_type": "audio"
                }
            ]
        })

        # Mock Popen
        process = MagicMock()
        process.stdin.write = MagicMock()
        process.communicate.return_value = (b"", b"")
        process.wait.return_value = None
        process.returncode = 0
        mock_popen.return_value = process

        yield {"run": mock_run, "popen": mock_popen, "process": process}

@pytest.fixture
def mock_renderers():
    with patch("backend.app.services.graphics_renderer.ActiveWordRenderer") as mock_active, \
         patch("backend.app.services.graphics_renderer.KaraokeRenderer") as mock_karaoke:

         # Mock render_frame to return a valid numpy array
         # shape (H, W, 4) - matches target resolution 1080x1920
         def create_frame(t):
             return np.zeros((1920, 1080, 4), dtype=np.uint8)

         mock_active.return_value.render_frame.side_effect = create_frame
         mock_karaoke.return_value.render_frame.side_effect = create_frame

         yield {"active": mock_active, "karaoke": mock_karaoke}

def test_get_video_metadata(mock_subprocess):
    # Test probe parsing
    w, h, fps, dur, has_audio = _get_video_metadata(Path("test.mp4"))
    assert w == 1920
    assert h == 1080
    assert fps == 30.0
    assert dur == 1.0
    assert has_audio is True

def test_render_active_word_video_pipeline(tmp_path, mock_subprocess, mock_renderers):
    # Call function
    output = tmp_path / "out.mp4"
    render_active_word_video(
        input_path=Path("in.mp4"),
        output_path=output,
        cues=[],
        max_lines=0, # ActiveWord
        target_width=1080,
        target_height=1920
    )

    # Verify probe called
    mock_subprocess["run"].assert_called()

    # Verify renderer init
    mock_renderers["active"].assert_called()

    # Verify ffmpeg command
    mock_subprocess["popen"].assert_called_once()
    args = mock_subprocess["popen"].call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "-f" in args and "rawvideo" in args
    assert "-filter_complex" in args
    assert str(output) in args

    # Verify frames written
    # 1.0s * 30fps = 30 frames
    assert mock_subprocess["process"].stdin.write.call_count == 30

def test_render_active_word_video_karaoke_mode(tmp_path, mock_subprocess, mock_renderers):
    output = tmp_path / "out.mp4"
    render_active_word_video(
        input_path=Path("in.mp4"),
        output_path=output,
        cues=[],
        max_lines=2, # Karaoke
        target_width=1080,
        target_height=1920
    )

    mock_renderers["karaoke"].assert_called()
    mock_subprocess["popen"].assert_called()
