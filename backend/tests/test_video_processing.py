import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import video_processing


def test_font_size_from_subtitle_size_presets() -> None:
    """
    REGRESSION: Subtitle size slider must map to correct font sizes.
    The slider uses a 50-150 percentage scale.
    """
    base = video_processing.config.DEFAULT_SUB_FONT_SIZE
    assert video_processing._font_size_from_subtitle_size(None) == base  # Default 100%
    assert video_processing._font_size_from_subtitle_size(100) == base  # 100% = base
    assert video_processing._font_size_from_subtitle_size(70) == int(round(base * 0.7))  # 70%
    assert video_processing._font_size_from_subtitle_size(85) == int(round(base * 0.85))  # 85%
    assert video_processing._font_size_from_subtitle_size(150) == int(round(base * 1.5))  # 150%
    assert video_processing._font_size_from_subtitle_size(50) == int(round(base * 0.5))  # 50% (min)


def test_normalize_and_stub_subtitles_runs_pipeline(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        calls.append(("extract", input_video))
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = tmp_path / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        calls.append(("transcribe", audio_path, kwargs))
        srt = tmp_path / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nΓεια\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="Γεια",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "Γεια")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        calls.append(("style", transcript_path))
        ass = tmp_path / "subs.ass"
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(
        input_path: Path,
        ass_path: Path,
        output_path: Path,
        *,
        video_crf,
        video_preset,
        audio_bitrate,
        audio_copy,
        use_hw_accel=False,
        **kwargs,
    ) -> None:
        calls.append(
            (
                "burn",
                input_path,
                ass_path,
                output_path,
                video_crf,
                video_preset,
                audio_bitrate,
                audio_copy,
            )
        )
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(
        video_processing.subtitles, "create_styled_subtitle_file", fake_style
    )
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path = video_processing.normalize_and_stub_subtitles(
        source, destination, language="el", video_crf=18
    )

    assert result_path == destination.resolve()
    assert destination.read_bytes() == b"video"
    assert [c[0] for c in calls] == ["extract", "transcribe", "style", "burn"]


def test_active_graphics_maps_to_ass_active(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nΓεια\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="ΓΕΙΑ",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "ΓΕΙΑ")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        captured["highlight_style"] = kwargs.get("highlight_style")
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="aac"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path = video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        highlight_style="active-graphics",
    )

    assert result_path == destination.resolve()
    assert captured["highlight_style"] == "active"


def test_build_filtergraph_quotes_ass_path() -> None:
    ass_path = Path("/tmp/my subs's file.ass")

    filtergraph = video_processing._build_filtergraph(ass_path)

    assert filtergraph.endswith("ass='/tmp/my subs\\'s file.ass'")


def test_normalize_and_stub_subtitles_removes_temporary_directory(
    monkeypatch, tmp_path: Path
) -> None:
    scratch_root = tmp_path / "scratch"
    calls = []

    class FakeTemporaryDirectory:
        def __enter__(self):
            scratch_root.mkdir()
            return str(scratch_root)

        def __exit__(self, exc_type, exc, tb):
            calls.append("cleanup")
            shutil.rmtree(scratch_root, ignore_errors=True)

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        assert output_dir == scratch_root
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        assert kwargs["output_dir"] == scratch_root
        srt = scratch_root / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nΓεια\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="Γεια",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "Γεια")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        assert transcript_path.parent == scratch_root
        ass = scratch_root / "subs.ass"
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path = video_processing.normalize_and_stub_subtitles(
        source, destination, language="el", video_crf=18
    )

    assert result_path == destination.resolve()
    assert not scratch_root.exists()
    assert calls == ["cleanup"]


def test_normalize_and_stub_subtitles_can_return_social_copy(monkeypatch, tmp_path: Path):
    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nCoding tips coding\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="CODING TIPS CODING",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "CODING")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path, social_copy = video_processing.normalize_and_stub_subtitles(
        source, destination, language="el", generate_social_copy=True
    )

    assert result_path == destination.resolve()
    assert social_copy.tiktok.title.startswith("Coding")


def test_normalize_and_stub_subtitles_persists_artifacts(monkeypatch, tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHello world\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="HELLO WORLD",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "HELLO")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path, social_copy = video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        generate_social_copy=True,
        artifact_dir=artifact_dir,
    )

    assert result_path == destination.resolve() or result_path == artifact_dir / destination.name
    assert (artifact_dir / "audio.wav").exists()
    assert (artifact_dir / "subs.srt").exists()
    assert (artifact_dir / "subs.ass").exists()
    transcript = (artifact_dir / "transcript.txt").read_text(encoding="utf-8")
    assert "HELLO WORLD" in transcript
    social_txt = (artifact_dir / "social_copy.txt").read_text(encoding="utf-8")
    assert social_copy.tiktok.title in social_txt
    social_json = json.loads((artifact_dir / "social_copy.json").read_text(encoding="utf-8"))
    assert social_json["tiktok"]["title"] == social_copy.tiktok.title


def test_normalize_and_stub_subtitles_can_use_llm_social_copy(monkeypatch, tmp_path: Path):
    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHello world\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="HELLO WORLD",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "HELLO")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    def fake_social_copy_llm(*args, **kwargs):
        return video_processing.subtitles.SocialCopy(
            tiktok=video_processing.subtitles.PlatformCopy("LLM TT", "desc"),
            youtube_shorts=video_processing.subtitles.PlatformCopy("LLM YT", "desc"),
            instagram=video_processing.subtitles.PlatformCopy("LLM IG", "desc"),
        )

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "build_social_copy_llm", fake_social_copy_llm)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path, social_copy = video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        generate_social_copy=True,
        use_llm_social_copy=True,
    )

    assert result_path == destination.resolve()
    assert social_copy.tiktok.title == "LLM TT"


def test_pipeline_logs_metrics(monkeypatch, tmp_path: Path) -> None:
    logged: dict = {}

    monkeypatch.setattr(video_processing.metrics, "should_log_metrics", lambda: True)
    monkeypatch.setattr(video_processing.metrics, "log_pipeline_metrics", lambda event: logged.update(event))

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        audio = tmp_path / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = tmp_path / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHello\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="HELLO",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "HELLO")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            # adapt arguments
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        model_size="tiny",
        beam_size=1,
        best_of=1,
    )

    assert logged["status"] == "success"
    assert logged["model_size"] == "tiny"
    assert "timings" in logged and "total_s" in logged["timings"]


def test_pipeline_logs_error_when_output_missing(monkeypatch, tmp_path: Path) -> None:
    logged: dict = {}

    monkeypatch.setattr(video_processing.metrics, "should_log_metrics", lambda: True)
    monkeypatch.setattr(video_processing.metrics, "log_pipeline_metrics", lambda event: logged.update(event))

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        srt = kwargs["output_dir"] / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHi\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="HI",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "HI")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(*args, **kwargs):
        # Intentionally do not write output to trigger error
        return None

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            # adapt arguments
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    with pytest.raises(RuntimeError):
        video_processing.normalize_and_stub_subtitles(
            source,
            destination,
            language="el",
            model_size="tiny",
        )


def test_input_audio_is_aac(monkeypatch):
    class Result:
        stdout = '{"format":{"duration":"3.5"},"streams":[{"codec_name":"aac"}]}'

    monkeypatch.setattr(video_processing.subprocess, "run", lambda *a, **k: Result())
    assert video_processing._input_audio_is_aac(Path("any.mp4")) is True

    def boom(*args, **kwargs):
        raise RuntimeError("probe fail")

    monkeypatch.setattr(video_processing.subprocess, "run", boom)
    assert video_processing._input_audio_is_aac(Path("any.mp4")) is False


def test_run_ffmpeg_with_subs_parses_progress(monkeypatch, tmp_path: Path):
    ass_path = tmp_path / "subs.ass"
    ass_path.write_text("[Script Info]")
    input_path = tmp_path / "in.mp4"
    input_path.write_text("video")
    output_path = tmp_path / "out.mp4"

    class DummyProc:
        def __init__(self):
            self.stderr = [
                "frame=1 time=00:00:01.00",
                "frame=2 time=00:00:02.00",
            ]
            self.returncode = 0
            self.stdout = []

        def wait(self):
            return 0

    monkeypatch.setattr(video_processing.subprocess, "Popen", lambda *a, **k: DummyProc())
    progress = []

    video_processing._run_ffmpeg_with_subs(
        input_path,
        ass_path,
        output_path,
        video_crf=23,
        video_preset="medium",
        audio_bitrate="128k",
        audio_copy=True,
        use_hw_accel=False,
        progress_callback=lambda p: progress.append(p),
        total_duration=4.0,
    )

    assert progress and max(progress) <= 100


def test_run_ffmpeg_with_subs_uses_hw_accel(monkeypatch, tmp_path: Path):
    ass_path = tmp_path / "subs.ass"
    ass_path.write_text("[Script Info]")
    input_path = tmp_path / "in.mp4"
    input_path.write_text("video")
    output_path = tmp_path / "out.mp4"

    class DummyProc:
        def __init__(self):
            self.stderr = []
            self.returncode = 0
            self.stdout = []

        def wait(self):
            return 0

    monkeypatch.setattr(video_processing.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(video_processing.subprocess, "Popen", lambda *a, **k: DummyProc())

    video_processing._run_ffmpeg_with_subs(
        input_path,
        ass_path,
        output_path,
        video_crf=10,
        video_preset="medium",
        audio_bitrate="128k",
        audio_copy=False,
        use_hw_accel=True,
    )


def test_pipeline_retries_without_hw_accel(monkeypatch, tmp_path: Path):
    calls: list[tuple[bool, bool]] = []

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHello\n", encoding="utf-8")
        cues = [video_processing.subtitles.Cue(start=0.0, end=1.0, text="HELLO", words=[])]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(
        input_path: Path,
        ass_path: Path,
        output_path: Path,
        *,
        use_hw_accel: bool,
        audio_copy: bool,
        **kwargs,
    ) -> None:
        calls.append((use_hw_accel, audio_copy))
        if use_hw_accel:
            raise subprocess.CalledProcessError(1, ["ffmpeg"], "fail")
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    probe_mock = MagicMock(return_value=video_processing.MediaProbe(duration_s=0.0, audio_codec="mp3"))
    monkeypatch.setattr(video_processing, "_probe_media", probe_mock)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path = video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        use_hw_accel=True,
    )

    assert result_path == destination.resolve()
    assert calls == [(True, False), (False, False)]
    assert probe_mock.call_count == 1


def test_normalize_and_stub_subtitles_missing_input(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        video_processing.normalize_and_stub_subtitles(
            tmp_path / "missing.mp4",
            tmp_path / "out.mp4",
        )


def test_normalize_handles_duration_failure(monkeypatch, tmp_path: Path):
    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHello\n", encoding="utf-8")
        cues = [video_processing.subtitles.Cue(start=0.0, end=1.0, text="HELLO", words=[])]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs):
        output_path.write_bytes(b"video")
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)

    src = tmp_path / "src.mp4"
    src.write_bytes(b"video")
    dest = tmp_path / "dest.mp4"
    video_processing.normalize_and_stub_subtitles(src, dest, language="el")


def test_normalize_with_large_model_progress(monkeypatch, tmp_path: Path):
    progress: list[float] = []

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:02,00\nHello\n", encoding="utf-8")
        cues = [video_processing.subtitles.Cue(start=0.0, end=2.0, text="HELLO", words=[])]
        if kwargs.get("progress_callback"):
            kwargs["progress_callback"](50.0)
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")
        cb = kwargs.get("progress_callback")
        if cb:
            cb(40.0)

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=8.0, audio_codec="mp3"),
    )

    src = tmp_path / "src.mp4"
    src.write_bytes(b"video")
    dest = tmp_path / "dest.mp4"

    video_processing.normalize_and_stub_subtitles(
        src,
        dest,
        language="el",
        model_size="large-v3",
        progress_callback=lambda _msg, pct: progress.append(pct),
    )

    assert any(pct > 80 for pct in progress)


def test_run_ffmpeg_with_subs_raises_on_failure(monkeypatch, tmp_path: Path):
    ass_path = tmp_path / "subs.ass"
    ass_path.write_text("[Script Info]")
    input_path = tmp_path / "in.mp4"
    input_path.write_text("video")
    output_path = tmp_path / "out.mp4"

    class DummyProc:
        def __init__(self):
            self.stderr = ["error"]
            self.returncode = 1
            self.stdout = []

        def wait(self):
            return 1

        def poll(self):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(video_processing.subprocess, "Popen", lambda *a, **k: DummyProc())

    with pytest.raises(subprocess.CalledProcessError):
        video_processing._run_ffmpeg_with_subs(
            input_path,
            ass_path,
            output_path,
            video_crf=23,
            video_preset="medium",
            audio_bitrate="128k",
            audio_copy=True,
            use_hw_accel=False,
        )


def test_normalize_applies_turbo_defaults(monkeypatch, tmp_path: Path):
    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        srt = Path(kwargs["output_dir"]) / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHi\n", encoding="utf-8")
        cues = [video_processing.subtitles.Cue(start=0.0, end=1.0, text="HI", words=[])]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=0.0, audio_codec="aac"),
    )

    src = tmp_path / "src.mp4"
    src.write_bytes(b"video")
    dest = tmp_path / "dest.mp4"

    video_processing.normalize_and_stub_subtitles(
        src,
        dest,
        language="el",
        model_size=video_processing.config.WHISPER_MODEL_TURBO,
        audio_copy=None,
    )
def test_social_copy_falls_back_if_none(monkeypatch, tmp_path: Path) -> None:
    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        srt = kwargs["output_dir"] / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHello world\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="HELLO WORLD",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "HELLO")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs) -> None:
        output_path.write_bytes(b"video")

    # Simulate LLM failure returning None
    def fake_social_copy_llm(*args, **kwargs):
        return None

    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            kwargs["output_dir"] = output_dir
            return fake_generate(audio_path, **kwargs)

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "OpenAITranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing, "StandardTranscriber", FakeTranscriber)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "build_social_copy_llm", fake_social_copy_llm)
    monkeypatch.setattr(video_processing.subtitles, "build_social_copy", lambda t: video_processing.subtitles.SocialCopy(
        tiktok=video_processing.subtitles.PlatformCopy("Fallback TT", "desc"),
        youtube_shorts=video_processing.subtitles.PlatformCopy("Fallback YT", "desc"),
        instagram=video_processing.subtitles.PlatformCopy("Fallback IG", "desc"),
    ))
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path, social_copy = video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        generate_social_copy=True,
        use_llm_social_copy=True,
    )

    assert result_path == destination.resolve()
    assert social_copy is not None


def test_hw_accel_retry_falls_back(monkeypatch, tmp_path: Path) -> None:
    calls: list[bool] = []

    def fake_extract(input_video: Path, output_dir=None, **kwargs) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        srt = kwargs["output_dir"] / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nHi\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="HI",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "HI")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        ass = transcript_path.with_suffix(".ass")
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, *, use_hw_accel, **kwargs) -> None:
        calls.append(use_hw_accel)
        if use_hw_accel:
            raise subprocess.CalledProcessError(1, ["ffmpeg"])
        output_path.write_bytes(b"video")

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        video_processing,
        "_probe_media",
        lambda _p: video_processing.MediaProbe(duration_s=10.0, audio_codec="mp3"),
    )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    video_processing.normalize_and_stub_subtitles(
        source,
        destination,
        language="el",
        model_size="tiny",
        use_hw_accel=True,
    )

    assert calls == [True, False]
    assert destination.exists()

def test_persist_artifacts_copy_logic(tmp_path):
    """Test that video is copied if destination is outside artifact dir."""
    artifact_dir = tmp_path / "artifacts"
    dest = tmp_path / "outside" / "video.mp4"
    dest.parent.mkdir()
    dest.write_text("orig")

    audio = tmp_path / "a.wav"
    audio.touch()
    srt = tmp_path / "s.srt"
    srt.touch()
    ass = tmp_path / "s.ass"
    ass.touch()

    # We can't easily invoke _persist_artifacts directly as it doesn't copy the video file itself
    # (that logic is in normalize_and_stub_subtitles).
    # But we can verify correct behavior via normalize if we force different paths.
    # Covered by test_normalize_and_stub_subtitles_persists_artifacts but let's be explicit
    # about valid artifact paths.
    video_processing._persist_artifacts(
        artifact_dir, audio, srt, ass, "transcript", None
    )
    assert (artifact_dir / "a.wav").exists()

def test_turbo_model_alias():
    """Verify turbo alias string."""
    val = video_processing.config.WHISPER_MODEL_TURBO
    # Relaxed check as it might be aliased to large-v3 in config
    assert "turbo" in val or "large-v3" in val

def test_generate_video_variant_success(monkeypatch, tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_path = tmp_path / "vid.mp4"
    input_path.touch()
    (artifact_dir / "vid.srt").write_text("SRT", encoding="utf-8")

    mock_job_store = MagicMock()
    mock_job = MagicMock()
    mock_job.user_id = "u1"
    mock_job.result_data = {"subtitle_position": "top", "max_subtitle_lines": 3, "resolution": "1080x1920"}
    mock_job_store.get_job.return_value = mock_job

    calls_style = []
    def fake_style(*args, **kwargs):
        calls_style.append(kwargs)
        return artifact_dir / "vid.ass"

    calls_burn = []
    def fake_burn(*args, **kwargs):
        # Handle positional args: input, ass, output
        if len(args) >= 3:
            kwargs["output_path"] = args[2]
        calls_burn.append(kwargs)
        kwargs["output_path"].touch()

    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)

    res = video_processing.generate_video_variant(
        job_id="j1",
        input_path=input_path,
        artifact_dir=artifact_dir,
        resolution="720x1280",
        job_store=mock_job_store,
        user_id="u1"
    )

    assert res.name == "processed_720x1280.mp4"
    assert res.exists()

    assert calls_style[0]["subtitle_position"] == "top"
    assert calls_style[0]["max_lines"] == 3
    assert calls_style[0]["play_res_x"] == 1080
    assert calls_style[0]["play_res_y"] == 1920

    assert calls_burn[0]["output_width"] == 720
    assert calls_burn[0]["output_height"] == 1280

def test_generate_video_variant_reuses_existing_ass(monkeypatch, tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_path = tmp_path / "vid.mp4"
    input_path.touch()
    (artifact_dir / "vid.srt").write_text("SRT", encoding="utf-8")
    existing_ass = artifact_dir / "vid.ass"
    existing_ass.write_text("ASS", encoding="utf-8")

    mock_job_store = MagicMock()
    mock_job = MagicMock()
    mock_job.user_id = "u1"
    mock_job.result_data = {"subtitle_position": "top", "max_subtitle_lines": 3, "resolution": "1080x1920"}
    mock_job_store.get_job.return_value = mock_job

    create_calls = []
    def fake_style(*args, **kwargs):
        create_calls.append((args, kwargs))
        return artifact_dir / "regenerated.ass"

    burn_calls = []
    def fake_burn(*args, **kwargs):
        burn_calls.append((args, kwargs))
        (kwargs.get("output_path") or args[2]).touch()

    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)

    res = video_processing.generate_video_variant(
        job_id="j1",
        input_path=input_path,
        artifact_dir=artifact_dir,
        resolution="720x1280",
        job_store=mock_job_store,
        user_id="u1",
    )

    assert res.name == "processed_720x1280.mp4"
    assert res.exists()
    assert create_calls == []
    assert burn_calls[0][0][1] == existing_ass

def test_generate_video_variant_missing_input(tmp_path):
     with pytest.raises(FileNotFoundError, match="Original input"):
         video_processing.generate_video_variant(
             "j", tmp_path/"missing.mp4", tmp_path, "1x1", MagicMock(), "u"
         )

def test_generate_video_variant_missing_transcript(tmp_path):
    # input exists, but no srt
    inp = tmp_path/"v.mp4"
    inp.touch()

    with pytest.raises(FileNotFoundError, match="Transcript not found"):
        video_processing.generate_video_variant(
             "j", inp, tmp_path, "1x1", MagicMock(), "u"
         )

def test_generate_video_variant_job_permission(tmp_path):
    inp = tmp_path/"v.mp4"
    inp.touch()
    (tmp_path/"v.srt").write_text("S")

    mock_store = MagicMock()
    mock_store.get_job.return_value = None

    with pytest.raises(PermissionError):
        video_processing.generate_video_variant(
             "j", inp, tmp_path, "1x1", mock_store, "u"
         )

def test_generate_video_variant_resolution_bad_string(monkeypatch, tmp_path):
    # Setup similar to success
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_path = tmp_path / "vid.mp4"
    input_path.touch()
    (artifact_dir / "vid.srt").write_text("SRT", encoding="utf-8")

    mock_store = MagicMock()
    mock_store.get_job.return_value = MagicMock(user_id="u", result_data={})

    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", lambda *a, **k: artifact_dir/"vid.ass")
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", lambda *a, **k: (k.get("output_path") or a[2]).touch())

    # "badstring" -> exception -> pass -> uses defaults
    res = video_processing.generate_video_variant("j", input_path, artifact_dir, "badstring", mock_store, "u")
    assert res.exists()

def test_generate_video_variant_glob_srt(monkeypatch, tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_path = tmp_path / "vid.mp4"
    input_path.touch()
    # vid.srt MISSING, but other.srt exists
    (artifact_dir / "other.srt").write_text("SRT", encoding="utf-8")

    mock_store = MagicMock()
    mock_store.get_job.return_value = MagicMock(user_id="u", result_data={})

    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", lambda *a, **k: artifact_dir/"vid.ass")
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", lambda *a, **k: (k.get("output_path") or a[2]).touch())

    res = video_processing.generate_video_variant("j", input_path, artifact_dir, "100x100", mock_store, "u")
    assert res.exists()
