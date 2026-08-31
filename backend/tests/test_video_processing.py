import shutil
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import (
    artifact_manager,
    ffmpeg_utils,
    settings_utils,
    subtitles,
    video_processing,
)
from backend.app.services.social_intelligence import SocialContent, SocialCopy
from backend.app.services.subtitle_types import Cue, WordTiming

pytest_plugins = ("backend.tests.video_processing_test_support",)


def test_font_size_from_subtitle_size_presets():
    """
    REGRESSION: Subtitle size slider must map to correct font sizes.
    The slider uses a 50-150 percentage scale.
    Base size is config.DEFAULT_SUB_FONT_SIZE (62).
    """
    # 50% of 62 = 31
    assert settings_utils.font_size_from_subtitle_size(50) == 31
    # 100% of 62 = 62
    assert settings_utils.font_size_from_subtitle_size(100) == 62
    # 150% of 62 = 93
    assert settings_utils.font_size_from_subtitle_size(150) == 93
    # None -> 62
    assert settings_utils.font_size_from_subtitle_size(None) == 62

    # Check clamping
    assert settings_utils.font_size_from_subtitle_size(10) == 31  # Clamped to 50%
    assert settings_utils.font_size_from_subtitle_size(200) == 93  # Clamped to 150%


def test_ass_font_calibration_matches_browser_visual_weight() -> None:
    """REGRESSION: libass rendered the same nominal font visibly smaller than CSS."""
    assert settings_utils.font_size_for_ass_rendering(31) == 35
    assert settings_utils.font_size_for_ass_rendering(62) == 69
    assert settings_utils.font_size_for_ass_rendering(93) == 104


def test_process_video_pipeline_runs_pipeline(monkeypatch, tmp_path: Path):
    # Mock all the heavy lifting
    input_video = tmp_path / "input.mp4"
    input_video.touch()

    def fake_extract(input_video: Path, output_dir=None, **kwargs):
        wav = output_dir / "audio.wav"
        wav.touch()
        return wav

    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi", encoding="utf-8")

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            return srt_file, [Cue(0, 1, "Hi")]

    def fake_style(transcript_path: Path, **kwargs):
        ass = transcript_path.with_suffix(".ass")
        ass.touch()
        return ass

    def fake_burn(
        input_path: Path,
        ass_path: Path,
        output_path: Path,
        *,
        video_crf=None,
        video_preset=None,
        audio_bitrate=None,
        audio_copy=False,
        use_hw_accel=False,
        **kwargs,
    ):
        output_path.touch()
        return str(output_path)

    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    # Correctly patch the symbol imported in video_processing
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "final.mp4"

    res = video_processing.process_video_pipeline(
        input_path=input_video,
        output_path=output_path,
        transcribe_provider="groq",
        transcribe_tier="standard",
    )

    assert res == output_path
    assert output_path.exists()


def test_elevenlabs_pipeline_reserves_weighted_provider_capacity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_video = tmp_path / "ten-minute.mp4"
    input_video.write_bytes(b"video")
    observed_slots: list[int] = []

    def fake_extract(
        _input_video: Path,
        *,
        output_dir: Path,
        **_kwargs: object,
    ) -> Path:
        audio_path = output_dir / "audio.wav"
        audio_path.touch()
        return audio_path

    class FakeScribeTranscriber:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def transcribe(
            self,
            _audio_path: Path,
            *,
            output_dir: Path,
            **_kwargs: object,
        ) -> tuple[Path, list[Cue]]:
            srt_path = output_dir / "captions.srt"
            srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nΓεια\n",
                encoding="utf-8",
            )
            return srt_path, [Cue(0, 1, "Γεια")]

    @contextmanager
    def fake_provider_capacity(
        *,
        slots_required: int,
        **_kwargs: object,
    ) -> Iterator[tuple[int, ...]]:
        observed_slots.append(slots_required)
        yield tuple(range(slots_required))

    monkeypatch.setattr(video_processing.settings, "mock_external_services", False)
    monkeypatch.setattr(video_processing.settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(
        video_processing.provider_clients,
        "resolve_elevenlabs_api_key",
        lambda: "test-elevenlabs-key",
    )
    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(
        video_processing,
        "ElevenLabsScribeTranscriber",
        FakeScribeTranscriber,
    )
    monkeypatch.setattr(
        video_processing,
        "lock_provider_transcription",
        fake_provider_capacity,
    )

    result = video_processing.process_video_pipeline(
        input_video,
        tmp_path / "artifacts" / "processed.mp4",
        artifact_dir=tmp_path / "artifacts",
        transcribe_provider="elevenlabs",
        transcribe_tier="pro",
        transcription_only=True,
        media_probe=ffmpeg_utils.MediaProbe(600.0, "aac"),
    )

    assert result.exists()
    assert observed_slots == [2]


def test_mock_transcription_finalizes_with_zero_provider_cost(monkeypatch, tmp_path: Path):
    # REGRESSION: The final ledger update used tier pricing without the resolved
    # provider, so a local mock run looked like billable external usage.
    input_video = tmp_path / "input.mp4"
    input_video.touch()

    def fake_extract(_input_video: Path, output_dir: Path, **_kwargs: object) -> Path:
        audio_path = output_dir / "audio.wav"
        audio_path.touch()
        return audio_path

    def fake_style(transcript_path: Path, **_kwargs: object) -> Path:
        ass_path = transcript_path.with_suffix(".ass")
        ass_path.touch()
        return ass_path

    def fake_burn(
        _input_path: Path,
        _ass_path: Path,
        output_path: Path,
        **_kwargs: object,
    ) -> None:
        output_path.touch()

    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(
        ffmpeg_utils,
        "probe_media",
        lambda _path: ffmpeg_utils.MediaProbe(12.0, "aac"),
    )

    ledger_store = MagicMock()
    reservation = types.SimpleNamespace(tier="standard", min_credits=25)
    charge_plan = types.SimpleNamespace(transcription=reservation)

    video_processing.process_video_pipeline(
        input_video,
        tmp_path / "out.mp4",
        transcribe_provider="mock",
        transcribe_tier="standard",
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    ledger_store.finalize.assert_called_once()
    finalize_kwargs = ledger_store.finalize.call_args.kwargs
    assert finalize_kwargs["cost_usd"] == 0.0
    assert finalize_kwargs["units"]["provider"] == "mock"
    assert finalize_kwargs["units"]["model"] == "mock-caption-v1"


def test_process_video_pipeline_falls_back_to_local_when_groq_key_missing(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "input.mp4"
    input_video.touch()

    def fake_extract(input_video: Path, output_dir=None, **kwargs):
        wav = output_dir / "audio.wav"
        wav.touch()
        return wav

    srt_file = tmp_path / "local.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi", encoding="utf-8")

    class FakeLocalTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            return srt_file, [Cue(0, 1, "Hi")]

    def fake_style(transcript_path: Path, **kwargs):
        ass = transcript_path.with_suffix(".ass")
        ass.touch()
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs):
        output_path.touch()
        return str(output_path)

    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    monkeypatch.setattr(video_processing.provider_clients, "resolve_groq_api_key", lambda: None)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", FakeLocalTranscriber)

    def fail_if_cloud_used(*args, **kwargs):
        raise AssertionError("Groq transcriber should not be used when GROQ_API_KEY is missing")

    monkeypatch.setattr(video_processing, "GroqTranscriber", fail_if_cloud_used)

    output_path = tmp_path / "final.mp4"
    result = video_processing.process_video_pipeline(
        input_path=input_video,
        output_path=output_path,
        transcribe_provider="groq",
        transcribe_tier="standard",
    )

    assert result == output_path
    assert output_path.exists()


def test_resolve_runtime_transcribe_provider_treats_empty_secret_as_missing(monkeypatch):
    # REGRESSION: config/secrets.toml may contain empty-string placeholders.
    # These must still trigger local fallback instead of pretending a cloud key exists.
    monkeypatch.setattr(video_processing.provider_clients, "resolve_groq_api_key", lambda: "")
    assert video_processing.resolve_runtime_transcribe_provider("groq") == "local"


def test_resolve_runtime_transcribe_provider_forces_mock_mode(monkeypatch):
    monkeypatch.setattr(video_processing.settings, "mock_external_services", True)
    monkeypatch.setattr(
        video_processing.provider_clients,
        "resolve_groq_api_key",
        lambda: "would-have-been-live",
    )

    assert video_processing.resolve_runtime_transcribe_provider("groq") == "mock"


def test_mock_mode_forces_scribe_without_resolving_a_key(monkeypatch):
    """REGRESSION: selecting the staged Scribe card must never escape mock mode."""
    monkeypatch.setattr(video_processing.settings, "mock_external_services", True)

    def fail_if_key_is_resolved():
        raise AssertionError("No ElevenLabs credential should be resolved in mock mode")

    monkeypatch.setattr(
        video_processing.provider_clients,
        "resolve_elevenlabs_api_key",
        fail_if_key_is_resolved,
    )

    assert video_processing.resolve_runtime_transcribe_provider("elevenlabs") == "mock"


def test_scribe_stays_disabled_outside_mock_until_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(video_processing.settings, "mock_external_services", False)
    monkeypatch.setattr(video_processing.settings, "elevenlabs_enabled", False)

    with pytest.raises(RuntimeError, match="disabled"):
        video_processing.resolve_runtime_transcribe_provider("elevenlabs")


def test_active_graphics_maps_to_ass_active(monkeypatch, tmp_path: Path):
    """
    Test that if UI sends 'active-graphics' highlight style,
    we map it to 'active' for the ASS generator if words exist.
    """
    input_video = tmp_path / "input.mp4"
    input_video.touch()

    # Capture arguments passed to style generator
    style_calls = []

    def fake_extract(input_video: Path, output_dir=None, **kwargs):
        wav = output_dir / "audio.wav"
        wav.touch()
        return wav

    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi", encoding="utf-8")

    def fake_style(transcript_path: Path, **kwargs):
        style_calls.append(kwargs)
        ass = transcript_path.with_suffix(".ass")
        ass.touch()
        return ass

    def fake_burn(input_path: Path, ass_path: Path, output_path: Path, **kwargs):
        output_path.touch()
        return str(output_path)

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            # Return words to ensure 'active' mode logic triggers
            cues = [Cue(0, 1, "Hi", words=[WordTiming(0, 1, "Hi")])]
            return srt_file, cues

    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    # Patch the class where it is used
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "final.mp4"

    video_processing.process_video_pipeline(
        input_path=input_video,
        output_path=output_path,
        transcribe_provider="groq",
        highlight_style="active-graphics",
        karaoke_enabled=True,
    )

    assert len(style_calls) == 1
    # Should be mapped to 'active' because words are present
    assert style_calls[0]["highlight_style"] == "active"


def test_build_filtergraph_quotes_ass_path():
    path = Path("/tmp/foo'bar.ass")
    fg = ffmpeg_utils.build_filtergraph(path)
    # Check escaping of single quote
    assert "foo\\'bar.ass" in fg or "foo'bar.ass" in fg or r"\'" in fg


def test_build_filtergraph_constrains_both_axes_for_extra_tall_video():
    fg = ffmpeg_utils.build_filtergraph(
        Path("/tmp/subtitles.ass"),
        target_width=720,
        target_height=1280,
    )

    assert ("scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2") in fg
    assert "pad=720:1280" in fg


def test_process_video_pipeline_removes_temporary_directory(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "input.mp4"
    input_video.touch()

    class FakeTemporaryDirectory:
        def __init__(self):
            self.name = str(tmp_path / "scratch")
            Path(self.name).mkdir(exist_ok=True)

        def __enter__(self):
            return self.name

        def __exit__(self, exc_type, exc, tb):
            shutil.rmtree(self.name)

    monkeypatch.setattr("tempfile.TemporaryDirectory", FakeTemporaryDirectory)

    # Mock everything else
    def fake_extract(input_video: Path, output_dir=None, **kwargs):
        wav = Path(output_dir) / "video.wav"
        wav.touch()
        return wav

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = Path(output_dir) / "test.srt"
            srt.touch()
            return srt, []

    def fake_style(transcript_path: Path, **kwargs):
        ass = transcript_path.with_suffix(".ass")
        ass.touch()
        return ass

    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()

    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(video_processing.subtitle_renderer, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "out.mp4"

    video_processing.process_video_pipeline(input_video, output_path, transcribe_provider="groq")

    # Check scratch is gone
    assert not (tmp_path / "scratch").exists()


def test_process_video_pipeline_can_return_social_copy(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()

    # Mock mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )

    # Need to touch output
    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            # Return dummy cues
            cues = [Cue(0, 10, "Hello world")]
            return srt, cues

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    # Mock social copy generation
    soc = SocialCopy(SocialContent("Title EL", "Title EN", "Desc EL", "Desc EN", ["#tag"]))
    monkeypatch.setattr(video_processing.social_intelligence, "build_social_copy", lambda text: soc)

    output_path = tmp_path / "out.mp4"
    path, copy = video_processing.process_video_pipeline(
        input_video, output_path, transcribe_provider="groq", generate_social_copy=True
    )

    assert copy == soc


def test_process_video_pipeline_persists_preview_asset_for_transcription_only(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.write_bytes(b"video")
    artifact_dir = tmp_path / "artifacts"

    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda _path: ffmpeg_utils.MediaProbe(10.0, "aac"))

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, [Cue(0, 10, "Hello world")]

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "artifacts" / "processed.mp4"
    res = video_processing.process_video_pipeline(
        input_video,
        output_path,
        transcribe_provider="groq",
        artifact_dir=artifact_dir,
        transcription_only=True,
    )

    assert res == output_path
    assert output_path.exists()
    assert output_path.read_bytes() == b"video"


def test_process_video_pipeline_persists_artifacts(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()
    artifact_dir = tmp_path / "artifacts"

    mock_persist = MagicMock()
    monkeypatch.setattr(artifact_manager, "persist_artifacts", mock_persist)

    # Mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )

    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)

    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, []

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    video_processing.process_video_pipeline(
        input_video, tmp_path / "out.mp4", transcribe_provider="groq", artifact_dir=artifact_dir
    )

    mock_persist.assert_called_once()
    assert mock_persist.call_args[0][0] == artifact_dir


def test_pipeline_logs_metrics(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()

    mock_metrics = MagicMock()
    from backend.app.core import metrics

    monkeypatch.setattr(metrics, "log_pipeline_metrics", mock_metrics)

    # Mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )

    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()

    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, []

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    video_processing.process_video_pipeline(input_video, tmp_path / "out.mp4", transcribe_provider="groq")

    mock_metrics.assert_called_once()
    data = mock_metrics.call_args[0][0]
    assert data["status"] == "success"
    assert "transcribe_s" in data["timings"]


def test_pipeline_logs_error_when_output_missing(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()

    # Mocks that FAIL to produce output video
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(
        video_processing.subtitle_renderer, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass"
    )
    monkeypatch.setattr(
        ffmpeg_utils, "run_ffmpeg_with_subs", lambda *args, **kwargs: None
    )  # Does nothing, file not created
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    class FakeTranscriber:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, []

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    # Should raise RuntimeError because output missing
    with pytest.raises(RuntimeError):
        video_processing.process_video_pipeline(input_video, tmp_path / "out.mp4", transcribe_provider="groq")
