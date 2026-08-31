import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import (
    ffmpeg_utils,
    video_processing,
)


def test_generate_video_variant_success(monkeypatch, tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mp4"
    input_video.touch()
    (artifact_dir / "in.srt").touch()

    # Mock job store
    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}  # Explicit dict
    job_store.get_job.return_value = job

    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )

    def fake_burn(*args, **kwargs):
        Path(args[2]).touch()  # args[2] is output_path

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    res = video_processing.generate_video_variant("job1", input_video, artifact_dir, "1280x720", job_store, "u1")
    assert res.exists()  # The fake output name


def test_generate_video_variant_publishes_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed re-render must not replace the last valid downloadable file."""
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mp4"
    input_video.write_bytes(b"input")
    (artifact_dir / "in.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        encoding="utf-8",
    )
    (artifact_dir / "in.ass").write_text("captions", encoding="utf-8")
    destination = artifact_dir / "processed_1280x720.mp4"
    destination.write_bytes(b"known-good-export")

    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}
    job_store.get_job.return_value = job

    def fail_after_partial_write(
        _input_path: Path,
        _ass_path: Path,
        output_path: Path,
        **_kwargs: object,
    ) -> None:
        output_path.write_bytes(b"partial-export")
        raise subprocess.CalledProcessError(1, ["ffmpeg"])

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fail_after_partial_write)

    with pytest.raises(subprocess.CalledProcessError):
        video_processing.generate_video_variant(
            "job1",
            input_video,
            artifact_dir,
            "1280x720",
            job_store,
            "u1",
        )

    assert destination.read_bytes() == b"known-good-export"
    assert list(artifact_dir.glob(".*.tmp.mp4")) == []


@pytest.mark.parametrize("audio_is_aac", [True, False])
def test_generate_video_variant_only_copies_compatible_aac_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    audio_is_aac: bool,
) -> None:
    # REGRESSION: PCM and other non-AAC tracks used to be copied into an MP4,
    # producing an export that was not reliably playable by web clients.
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mov"
    input_video.touch()
    (artifact_dir / "in.srt").touch()
    (artifact_dir / "in.ass").touch()

    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}
    job_store.get_job.return_value = job

    captured: dict[str, bool] = {}

    def fake_burn(
        _input_path: Path,
        _ass_path: Path,
        output_path: Path,
        **kwargs: object,
    ) -> None:
        selected_audio_copy = kwargs.get("audio_copy")
        assert isinstance(selected_audio_copy, bool)
        captured["audio_copy"] = selected_audio_copy
        output_path.touch()

    monkeypatch.setattr(ffmpeg_utils, "input_audio_is_aac", lambda _path: audio_is_aac)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    video_processing.generate_video_variant("job1", input_video, artifact_dir, "1280x720", job_store, "u1")

    assert captured["audio_copy"] is audio_is_aac


def test_generate_video_variant_reuses_existing_ass(monkeypatch, tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mp4"
    input_video.touch()
    (artifact_dir / "in.srt").touch()
    (artifact_dir / "in.ass").touch()  # exists

    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}
    job_store.get_job.return_value = job

    # Should NOT call create_styled_subtitle_file if no settings passed
    create_mock = MagicMock()
    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", create_mock)

    def fake_burn(*args, **kwargs):
        Path(args[2]).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    video_processing.generate_video_variant("job1", input_video, artifact_dir, "1280x720", job_store, "u1")

    create_mock.assert_not_called()


def test_generate_video_variant_resolution_bad_string(tmp_path):
    input_video = tmp_path / "i"
    input_video.touch()

    with pytest.raises(ValueError, match="Invalid resolution format"):
        video_processing.generate_video_variant("j", input_video, tmp_path / "a", "badres", None, "u")


def test_generate_video_variant_glob_srt(monkeypatch, tmp_path):
    # Verify fallback to glob *.srt if specific name not found
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mp4"
    input_video.touch()
    (artifact_dir / "other.srt").touch()

    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}
    job_store.get_job.return_value = job

    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )

    def fake_burn(*args, **kwargs):
        Path(args[2]).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    # Should pass finding other.srt
    res = video_processing.generate_video_variant("job1", input_video, artifact_dir, "1280x720", job_store, "u1")
    assert res.exists()


def test_generate_video_variant_active_graphics_maps_to_active(monkeypatch, tmp_path: Path):
    """
    REGRESSION: generate_video_variant must convert 'active-graphics' to 'active'
    for proper subtitle highlighting in exports.
    """
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mp4"
    input_video.touch()
    (artifact_dir / "in.srt").touch()

    # Create transcription.json with word timings
    transcription_data = [
        {
            "start": 0,
            "end": 1,
            "text": "Hello world",
            "words": [{"start": 0, "end": 0.5, "text": "Hello"}, {"start": 0.5, "end": 1, "text": "world"}],
        }
    ]
    (artifact_dir / "transcription.json").write_text(json.dumps(transcription_data), encoding="utf-8")

    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}
    job_store.get_job.return_value = job

    # Capture kwargs passed to create_styled_subtitle_file
    style_calls = []
    ass_output = artifact_dir / "in.ass"

    def capture_style(*args, **kwargs):
        style_calls.append(kwargs)
        ass_output.touch()  # Create the file so fallback path is not triggered
        return ass_output

    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", capture_style)

    def fake_burn(*args, **kwargs):
        Path(args[2]).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    # Call with active-graphics highlight style
    video_processing.generate_video_variant(
        "job1",
        input_video,
        artifact_dir,
        "1280x720",
        job_store,
        "u1",
        subtitle_settings={
            "highlight_style": "active-graphics",
            "karaoke_enabled": True,
            "subtitle_size": 100,
        },
    )

    # Should be mapped to 'active' because words are present
    assert len(style_calls) == 1
    assert style_calls[0]["highlight_style"] == "active", (
        f"Expected 'active' but got '{style_calls[0]['highlight_style']}'"
    )
