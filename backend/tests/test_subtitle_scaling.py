from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.core import config
from backend.app.services import video_processing

# Mock config to ensure stable defaults
config.DEFAULT_WIDTH = 1080
config.DEFAULT_HEIGHT = 1920

def test_ass_generation_forces_1080p_playres():
    """
    Verify that ASS generation uses 1080x1920 PlayRes
    even if the output resolution is different (e.g. 720p).
    """
    with patch("backend.app.services.video_processing.subtitles.create_styled_subtitle_file") as mock_create_ass, \
         patch("backend.app.services.video_processing.Path.exists", return_value=True), \
         patch("backend.app.services.video_processing.probe_media") as mock_probe, \
         patch("backend.app.services.video_processing.subtitles.extract_audio") as mock_extract, \
         patch("backend.app.services.video_processing._run_ffmpeg_with_subs"):

        # Setup mocks
        mock_probe.return_value = MagicMock(duration_s=10, audio_codec="aac")
        mock_extract.return_value = Path("/tmp/dummy_audio.wav")

        # Dummy inputs
        input_path = Path("/tmp/input.mp4")
        output_path = Path("/tmp/output.mp4")
        artifact_dir = Path("/tmp/artifacts")

        video_processing.normalize_and_stub_subtitles(
            input_path=input_path,
            output_path=output_path,
            artifact_dir=artifact_dir,
            output_width=720,
            output_height=1280,
            transcribe_provider="local",
            check_cancelled=lambda: None
        )

        # Verify call args
        args, kwargs = mock_create_ass.call_args

        # Critical assertion: PlayResX/Y must be 1080/1920
        assert kwargs["play_res_x"] == 1080
        assert kwargs["play_res_y"] == 1920

def test_generate_video_variant_forces_1080p_playres():
    """Verify export logic also forces 1080p reference."""
    with patch("backend.app.services.video_processing.subtitles.create_styled_subtitle_file") as mock_create_ass, \
         patch("backend.app.services.video_processing.Path.exists", return_value=True), \
         patch("backend.app.services.video_processing.probe_media"), \
         patch("backend.app.services.video_processing._run_ffmpeg_with_subs"):

        job_id = "test_job"
        user_id = "user123"
        input_path = Path("/tmp/input.mp4")
        artifact_dir = Path("/tmp/artifacts")

        # Mock job store
        mock_job_store = MagicMock()
        mock_job = MagicMock()
        mock_job.user_id = user_id
        # generate_video_variant doesn't use job object directly for permission check?
        # Actually it does NOT check permissions internally usually, it assumes caller did?
        # Check source: it takes job_store but does it use it?
        # Ah, it uses it to update progress?
        # Wait, the error was: `job = job_store.get_job(job_id); if not job ...`
        # So it DOES fetch job.

        mock_job_store.get_job.return_value = mock_job

        # Mock finding transcription.json
        with patch.object(Path, "read_text", return_value="[]"):
            video_processing.generate_video_variant(
                job_id=job_id,
                input_path=input_path,
                artifact_dir=artifact_dir,
                resolution="720x1280",
                job_store=mock_job_store,
                user_id=user_id,
                subtitle_settings={"max_subtitle_lines": 2}
            )

            # Verify call args
            args, kwargs = mock_create_ass.call_args
            assert kwargs["play_res_x"] == 1080
            assert kwargs["play_res_y"] == 1920
