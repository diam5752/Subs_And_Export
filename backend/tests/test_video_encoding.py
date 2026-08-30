import json
import select
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import (
    artifact_manager,
    ffmpeg_utils,
    subtitles,
    video_processing,
)
from backend.app.services.social_intelligence import SocialContent, SocialCopy
from backend.app.services.subtitle_types import Cue, WordTiming

pytest_plugins = ("backend.tests.video_processing_test_support",)


def test_input_audio_is_aac(monkeypatch, tmp_path: Path):
    f = tmp_path / "test.mp4"
    f.touch()

    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    assert ffmpeg_utils.input_audio_is_aac(f) is True

    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "mp3"))
    assert ffmpeg_utils.input_audio_is_aac(f) is False


def test_run_ffmpeg_with_subs_parses_progress(monkeypatch, tmp_path: Path):
    # This tests the progress parsing inside run_ffmpeg_with_subs.
    # We need to simulate stderr output.

    class MockProcess:
        def __init__(self, *args, **kwargs):
            self.stderr = MagicMock()
            # Simulate a time line and then EOF
            self.stderr.readline.side_effect = ["frame=100 time=00:00:05.00 bitrate=100k\n", ""]
            self.returncode = 0

        def wait(self):
            pass

        def poll(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", MockProcess)

    # Mock select to avoid fileno() error
    # We return [process.stderr] as ready to read
    monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r[0]], [], []))

    progress_mock = MagicMock()
    ffmpeg_utils.run_ffmpeg_with_subs(
        tmp_path / "in.mp4",
        tmp_path / "sub.ass",
        tmp_path / "out.mp4",
        video_crf=23,
        video_preset="fast",
        audio_bitrate="128k",
        audio_copy=False,
        progress_callback=progress_mock,
        total_duration=10.0,
    )

    # Check if progress callback called. 5s / 10s = 50%
    progress_mock.assert_called()
    args = progress_mock.call_args[0]
    assert args[0] == 50.0


def test_run_ffmpeg_with_subs_uses_hw_accel(monkeypatch, tmp_path: Path):
    class MockProcess:
        def __init__(self, cmd, *args, **kwargs):
            self.cmd = cmd
            self.stderr = MagicMock()
            self.stderr.readline.return_value = ""
            self.returncode = 0

        def wait(self):
            pass

        def poll(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", MockProcess)
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r[0]], [], []))

    calls = []

    def spy_popen(cmd, *args, **kwargs):
        calls.append(cmd)
        return MockProcess(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy_popen)

    ffmpeg_utils.run_ffmpeg_with_subs(
        tmp_path / "in.mp4",
        tmp_path / "sub.ass",
        tmp_path / "out.mp4",
        video_crf=23,
        video_preset="fast",
        audio_bitrate="128k",
        audio_copy=False,
        use_hw_accel=True,
    )

    cmd = calls[0]
    assert "-c:v" in cmd
    assert "h264_videotoolbox" in cmd


def test_pipeline_retries_without_hw_accel(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "in.mp4"
    input_video.touch()

    # Mock first ffmpeg call fails, second succeeds and creates FILE
    def side_effect(input_path, ass_path, destination, **kwargs):
        if kwargs.get("use_hw_accel") is True:
            raise subprocess.CalledProcessError(1, "cmd")
        # Else success: touch file
        Path(destination).touch()
        return None

    ffmpeg_mock = MagicMock(side_effect=side_effect)

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", ffmpeg_mock)

    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            return (output_dir / "a.srt", [])

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    video_processing.process_video_pipeline(
        input_video, tmp_path / "out.mp4", transcribe_provider="groq", use_hw_accel=True
    )

    assert ffmpeg_mock.call_count == 2
    # First call with True, second with False
    assert ffmpeg_mock.call_args_list[0][1]["use_hw_accel"] is True
    assert ffmpeg_mock.call_args_list[1][1]["use_hw_accel"] is False


def test_normalize_handles_duration_failure(monkeypatch, tmp_path: Path):
    # If probe fails, total_duration is 0, logic should proceed without progress
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(None, None))

    input_video = tmp_path / "in.mp4"
    input_video.touch()

    # Mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )

    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            return (output_dir / "a.srt", [])

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    # Should not crash
    video_processing.process_video_pipeline(input_video, tmp_path / "out.mp4", transcribe_provider="groq")


def test_normalize_with_large_model_progress():
    # Progress callback testing logic wrapper
    pass


def test_run_ffmpeg_with_subs_raises_safe_error_on_failure(monkeypatch, tmp_path: Path):
    # Mock subprocess to return error code
    class MockProcess:
        def __init__(self, *args, **kwargs):
            self.stderr = MagicMock()
            self.stderr.readline.return_value = "Padded dimensions cannot be smaller than input dimensions.\n"
            self.returncode = 1  # Error!

        def wait(self):
            pass

        def poll(self):
            return 1

        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", MockProcess)
    monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r[0]], [], []))

    with pytest.raises(ffmpeg_utils.FFmpegRenderError) as raised:
        ffmpeg_utils.run_ffmpeg_with_subs(
            tmp_path / "in",
            tmp_path / "sub",
            tmp_path / "out",
            video_crf=23,
            video_preset="f",
            audio_bitrate="k",
            audio_copy=False,
        )

    assert str(raised.value) == "Video rendering failed."
    assert "ffmpeg" not in str(raised.value)
    assert "Padded dimensions" in raised.value.stderr
    assert "Padded dimensions" not in str(raised.value)


def test_persist_artifacts_copies_sources_and_writes_bilingual_social_copy(tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    audio_path = tmp_path / "audio.wav"
    srt_path = tmp_path / "captions.srt"
    ass_path = tmp_path / "captions.ass"
    for path in (audio_path, srt_path, ass_path):
        path.write_text(path.name, encoding="utf-8")

    social_copy = SocialCopy(
        generic=SocialContent(
            title_el="Ελληνικός τίτλος",
            title_en="English title",
            description_el="Ελληνική περιγραφή",
            description_en="English description",
            hashtags=["#subframe"],
        )
    )

    artifact_manager.persist_artifacts(
        artifact_dir,
        audio_path,
        srt_path,
        ass_path,
        "Μεταγραφή",
        social_copy,
    )

    assert (artifact_dir / audio_path.name).read_text(encoding="utf-8") == audio_path.name
    assert (artifact_dir / srt_path.name).read_text(encoding="utf-8") == srt_path.name
    assert (artifact_dir / ass_path.name).read_text(encoding="utf-8") == ass_path.name
    social_json = json.loads((artifact_dir / "social_copy.json").read_text(encoding="utf-8"))
    assert social_json == {
        "title_el": "Ελληνικός τίτλος",
        "description_el": "Ελληνική περιγραφή",
        "title_en": "English title",
        "description_en": "English description",
        "hashtags": ["#subframe"],
    }


def test_persist_artifacts_resegments_transcription_json(tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    audio_path = tmp_path / "audio.wav"
    srt_path = tmp_path / "captions.srt"
    ass_path = tmp_path / "captions.ass"
    for path in (audio_path, srt_path, ass_path):
        path.write_text("x", encoding="utf-8")

    words = [
        WordTiming(start=i * 0.4, end=(i + 1) * 0.4, text=text)
        for i, text in enumerate(
            [
                "ΓΕΙΑ",
                "ΣΑΣ,",
                "ΜΕ",
                "ΛΕΝΕ",
                "ΙΑΝΝΗ.",
                "ΕΙΜΑΙ",
                "ΑΠΟ",
                "ΤΗΝ",
                "ΑΜΕΡΙΚΗ.",
                "Ο",
                "ΠΑΤΕΡΑΣ",
                "ΜΟΥ",
                "ΕΙΝΑΙ",
                "ΑΠΟ",
                "ΤΗΝ",
                "ΜΑΚΕΔΟΝΙΑ,",
                "ΣΕΡΡΕΣ,",
                "ΑΛΛΑ",
                "Ο",
                "ΠΑΠΠΟΥΣ",
                "ΜΟΥ",
                "ΚΑΙ",
                "Η",
                "ΓΙΑΓΙΑ",
                "ΜΟΥ",
                "ΗΤΑΝ",
                "ΠΡΟΣΦΥΓΕΣ",
                "ΑΠΟ",
                "ΤΗΝ",
                "ΘΡΑΚΗ.",
            ]
        )
    ]
    cue = Cue(
        start=0.0,
        end=words[-1].end,
        text=" ".join(word.text for word in words),
        words=words,
    )

    artifact_manager.persist_artifacts(
        artifact_dir,
        audio_path,
        srt_path,
        ass_path,
        cue.text,
        social_copy=None,
        cues=[cue],
        max_subtitle_lines=2,
        subtitle_size=85,
    )

    transcription = json.loads((artifact_dir / "transcription.json").read_text(encoding="utf-8"))
    assert len(transcription) >= 2
    assert transcription[0]["end"] < cue.end
    assert transcription[0]["words"]
    assert any("ΘΡΑΚΗ" in entry["text"] for entry in transcription)


def test_artifact_delivery_can_preserve_cues_without_resegmentation() -> None:
    cue = Cue(start=0.0, end=1.0, text="unchanged")

    prepared = artifact_manager._prepare_cues_for_delivery(
        [cue],
        max_subtitle_lines=0,
        subtitle_size=100,
    )

    assert [(item.start, item.end, item.text) for item in prepared] == [
        (0.0, 1.0, "unchanged"),
    ]
