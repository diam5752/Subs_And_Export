import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.services.video_processing import _run_ffmpeg_with_subs


def test_run_ffmpeg_deadlock_prevention():
    """
    Verify that _run_ffmpeg_with_subs uses DEVNULL for stdout to prevent deadlocks.
    Using PIPE for stdout without reading it causes deadlock if the buffer fills up.
    """
    input_path = Path("test_input.mp4")
    ass_path = Path("test.ass")
    output_path = Path("test_output.mp4")

    with patch("subprocess.Popen") as mock_popen:
        # Configure mock to behave enough like Popen to not crash the function
        process_mock = MagicMock()
        # Mock stderr as a list of strings (which is iterable)
        process_mock.stderr = ["line1", "time=00:00:01.00", "line2"]

        process_mock.wait.return_value = None
        process_mock.returncode = 0
        process_mock.poll.return_value = 0

        mock_popen.return_value = process_mock

        # Call the function
        try:
            _run_ffmpeg_with_subs(
                input_path, ass_path, output_path,
                video_crf=20, video_preset="fast", audio_bitrate="128k", audio_copy=False
            )
        except Exception as e:
            # We don't care if it fails due to logic errors, we just want to check Popen call
            pass

        # Verify call args
        args, kwargs = mock_popen.call_args

        # Check that stdout was set to DEVNULL
        # subprocess.PIPE is -1, DEVNULL is -3
        assert kwargs.get("stdout") == subprocess.DEVNULL, \
            f"stdout was {kwargs.get('stdout')}, expected subprocess.DEVNULL to prevent deadlock"
