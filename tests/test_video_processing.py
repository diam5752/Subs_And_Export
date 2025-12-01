import json
import shutil
from pathlib import Path

import pytest
import subprocess

from greek_sub_publisher import video_processing


def test_normalize_and_stub_subtitles_runs_pipeline(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    def fake_get_duration(path: Path) -> float:
        return 10.0

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(
        video_processing.subtitles, "generate_subtitles_from_audio", fake_generate
    )
    monkeypatch.setattr(
        video_processing.subtitles, "create_styled_subtitle_file", fake_style
    )
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", fake_get_duration)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path = video_processing.normalize_and_stub_subtitles(
        source, destination, language="el", video_crf=18
    )

    assert result_path == destination.resolve()
    assert destination.read_bytes() == b"video"
    assert [c[0] for c in calls] == ["extract", "transcribe", "style", "burn"]


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

    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    monkeypatch.setattr(video_processing.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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
    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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

    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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
    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    def fake_social_copy_llm(transcript_text: str, **kwargs):
        return video_processing.subtitles.SocialCopy(
            tiktok=video_processing.subtitles.PlatformCopy("LLM TT", "desc"),
            youtube_shorts=video_processing.subtitles.PlatformCopy("LLM YT", "desc"),
            instagram=video_processing.subtitles.PlatformCopy("LLM IG", "desc"),
        )

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "build_social_copy_llm", fake_social_copy_llm)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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

    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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

    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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

    assert logged["status"] == "error"
    assert "Output video was not produced" in logged["error"]


def test_social_copy_falls_back_if_none(monkeypatch, tmp_path: Path) -> None:
    def fake_extract(input_video: Path, output_dir=None) -> Path:
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

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", fake_generate)
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(video_processing.subtitles, "build_social_copy_llm", fake_social_copy_llm)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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

    def fake_extract(input_video: Path, output_dir=None) -> Path:
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
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda p: 10.0)
    monkeypatch.setattr(video_processing, "_input_audio_is_aac", lambda _p: False)

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
