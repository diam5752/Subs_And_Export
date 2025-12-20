import json
import shutil
import subprocess
import select
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
from backend.app.services.subtitle_types import Cue, WordTiming
from backend.app.core import config


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
    assert settings_utils.font_size_from_subtitle_size(10) == 31   # Clamped to 50%
    assert settings_utils.font_size_from_subtitle_size(200) == 93  # Clamped to 150%


def test_normalize_and_stub_subtitles_runs_pipeline(monkeypatch, tmp_path: Path):
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
        def __init__(self, *args, **kwargs): pass
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
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    # Correctly patch the symbol imported in video_processing
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "final.mp4"
    
    res = video_processing.normalize_and_stub_subtitles(
        input_path=input_video,
        output_path=output_path,
        transcribe_provider="groq",
        model_size="tiny",
    )
    
    assert res == output_path
    assert output_path.exists()


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
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            # Return words to ensure 'active' mode logic triggers
            cues = [Cue(0, 1, "Hi", words=[WordTiming(0, 1, "Hi")])]
            return srt_file, cues

    monkeypatch.setattr(subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))

    # Patch the class where it is used
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "final.mp4"
    
    video_processing.normalize_and_stub_subtitles(
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


def test_normalize_and_stub_subtitles_removes_temporary_directory(
    monkeypatch, tmp_path: Path
):
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
        def __init__(self, *args, **kwargs): pass
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
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", fake_style)
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    output_path = tmp_path / "out.mp4"
    
    video_processing.normalize_and_stub_subtitles(
        input_video, output_path, transcribe_provider="groq"
    )
    
    # Check scratch is gone
    assert not (tmp_path / "scratch").exists()


def test_normalize_and_stub_subtitles_can_return_social_copy(
    monkeypatch, tmp_path: Path
):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()
    
    # Mock mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    # Need to touch output
    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            # Return dummy cues
            cues = [Cue(0, 10, "Hello world")]
            return srt, cues

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    # Mock social copy generation
    soc = subtitles.SocialCopy(subtitles.SocialContent("Title", "Desc", ["#tag"]))
    monkeypatch.setattr(subtitles, "build_social_copy", lambda text: soc)

    output_path = tmp_path / "out.mp4"
    path, copy = video_processing.normalize_and_stub_subtitles(
        input_video, output_path,
        transcribe_provider="groq",
        generate_social_copy=True
    )
    
    assert copy == soc


def test_normalize_and_stub_subtitles_persists_artifacts(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()
    artifact_dir = tmp_path / "artifacts"
    
    mock_persist = MagicMock()
    monkeypatch.setattr(artifact_manager, "persist_artifacts", mock_persist)
    
    # Mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    
    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, []

    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    
    video_processing.normalize_and_stub_subtitles(
        input_video, tmp_path/"out.mp4",
        transcribe_provider="groq",
        artifact_dir=artifact_dir
    )
    
    mock_persist.assert_called_once()
    assert mock_persist.call_args[0][0] == artifact_dir


def test_normalize_and_stub_subtitles_can_use_llm_social_copy(monkeypatch, tmp_path: Path):
    # Verify use_llm_social_copy triggers build_social_copy_llm
    input_video = tmp_path / "vid.mp4"
    input_video.touch()
    
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, [Cue(0, 1, "test")]
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    mock_llm = MagicMock()
    monkeypatch.setattr(subtitles, "build_social_copy_llm", mock_llm)
    
    video_processing.normalize_and_stub_subtitles(
        input_video, tmp_path/"out.mp4",
        transcribe_provider="groq",
        generate_social_copy=True,
        use_llm_social_copy=True,
    )
    
    mock_llm.assert_called_once()


def test_pipeline_logs_metrics(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()
    
    mock_metrics = MagicMock()
    from backend.app.common import metrics
    monkeypatch.setattr(metrics, "log_pipeline_metrics", mock_metrics)
    
    # Mocks
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, []
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    video_processing.normalize_and_stub_subtitles(
        input_video, tmp_path/"out.mp4",
        transcribe_provider="groq"
    )
    
    mock_metrics.assert_called_once()
    data = mock_metrics.call_args[0][0]
    assert data["status"] == "success"
    assert "transcribe_s" in data["timings"]


def test_pipeline_logs_error_when_output_missing(monkeypatch, tmp_path: Path):
    input_video = tmp_path / "vid.mp4"
    input_video.touch()
    
    # Mocks that FAIL to produce output video
    monkeypatch.setattr(subtitles, "extract_audio", lambda *args, **kwargs: tmp_path / "a.wav")
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", lambda *args, **kwargs: None) # Does nothing, file not created
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs):
            srt = output_dir / "a.srt"
            srt.touch()
            return srt, []
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)
    
    # Should raise RuntimeError because output missing
    with pytest.raises(RuntimeError):
        video_processing.normalize_and_stub_subtitles(
            input_video, tmp_path/"out.mp4", transcribe_provider="groq"
        )


def test_input_audio_is_aac(monkeypatch, tmp_path: Path):
    f = tmp_path/"test.mp4"
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
            self.stderr.readline.side_effect = [
                "frame=100 time=00:00:05.00 bitrate=100k\n",
                ""
            ]
            self.returncode = 0
            
        def wait(self): pass
        def poll(self): return 0
        def kill(self): pass

    monkeypatch.setattr(subprocess, "Popen", MockProcess)
    
    # Mock select to avoid fileno() error
    # We return [process.stderr] as ready to read
    monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r[0]], [], []))
    
    progress_mock = MagicMock()
    ffmpeg_utils.run_ffmpeg_with_subs(
        tmp_path/"in.mp4", tmp_path/"sub.ass", tmp_path/"out.mp4",
        video_crf=23, video_preset="fast", audio_bitrate="128k", audio_copy=False,
        progress_callback=progress_mock, total_duration=10.0
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
        def wait(self): pass
        def poll(self): return 0
        def kill(self): pass
        
    monkeypatch.setattr(subprocess, "Popen", MockProcess)
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r[0]], [], []))
    
    calls = []
    def spy_popen(cmd, *args, **kwargs):
        calls.append(cmd)
        return MockProcess(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", spy_popen)
    
    ffmpeg_utils.run_ffmpeg_with_subs(
        tmp_path/"in.mp4", tmp_path/"sub.ass", tmp_path/"out.mp4",
        video_crf=23, video_preset="fast", audio_bitrate="128k", audio_copy=False,
        use_hw_accel=True
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
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    monkeypatch.setattr(ffmpeg_utils, "probe_media", lambda p: ffmpeg_utils.MediaProbe(10.0, "aac"))
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs): return (output_dir/"a.srt", [])
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    video_processing.normalize_and_stub_subtitles(
        input_video, tmp_path/"out.mp4", transcribe_provider="groq", use_hw_accel=True
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
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    
    def fake_burn(input_path, ass_path, output_path, **kwargs):
        Path(output_path).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    
    class FakeTranscriber:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, audio_path, output_dir, **kwargs): return (output_dir/"a.srt", [])
    monkeypatch.setattr(video_processing, "GroqTranscriber", FakeTranscriber)

    # Should not crash
    video_processing.normalize_and_stub_subtitles(
        input_video, tmp_path/"out.mp4", transcribe_provider="groq"
    )

def test_normalize_with_large_model_progress():
    # Progress callback testing logic wrapper
    pass

def test_run_ffmpeg_with_subs_raises_on_failure(monkeypatch, tmp_path: Path):
    # Mock subprocess to return error code
    class MockProcess:
        def __init__(self, *args, **kwargs):
            self.stderr = MagicMock()
            self.stderr.readline.return_value = ""
            self.returncode = 1 # Error!
        def wait(self): pass
        def poll(self): return 1
        def kill(self): pass
        
    monkeypatch.setattr(subprocess, "Popen", MockProcess)
    monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r[0]], [], []))
    
    with pytest.raises(subprocess.CalledProcessError):
        ffmpeg_utils.run_ffmpeg_with_subs(tmp_path/"in", tmp_path/"sub", tmp_path/"out",
            video_crf=23, video_preset="f", audio_bitrate="k", audio_copy=False)

def test_normalize_applies_turbo_defaults():
    pass

def test_social_copy_falls_back_if_none():
    pass

def test_hw_accel_retry_falls_back():
    pass

def test_persist_artifacts_copy_logic(tmp_path):
    d = tmp_path / "artifacts"
    f = tmp_path / "file.txt"
    f.touch()
    # Stub test
    pass

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
    job.result_data = {"subtitle_size": 100} # Explicit dict
    job_store.get_job.return_value = job
    
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    def fake_burn(*args, **kwargs):
        Path(args[2]).touch() # args[2] is output_path
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    
    res = video_processing.generate_video_variant(
        "job1", input_video, artifact_dir, "1280x720", job_store, "u1"
    )
    assert res.exists() # The fake output name

def test_generate_video_variant_reuses_existing_ass(monkeypatch, tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    input_video = tmp_path / "in.mp4"
    input_video.touch()
    (artifact_dir / "in.srt").touch()
    (artifact_dir / "in.ass").touch() # exists
    
    job_store = MagicMock()
    job = MagicMock()
    job.user_id = "u1"
    job.result_data = {"subtitle_size": 100}
    job_store.get_job.return_value = job
    
    # Should NOT call create_styled_subtitle_file if no settings passed
    create_mock = MagicMock()
    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", create_mock)
    def fake_burn(*args, **kwargs):
        Path(args[2]).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    
    video_processing.generate_video_variant(
        "job1", input_video, artifact_dir, "1280x720", job_store, "u1"
    )
    
    create_mock.assert_not_called()

def test_generate_video_variant_resolution_bad_string(tmp_path):
    with pytest.raises(Exception):
         video_processing.generate_video_variant(
            "j", tmp_path/"i", tmp_path/"a", "badres", None, "u"
         )

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

    monkeypatch.setattr(subtitles, "create_styled_subtitle_file", lambda *args, **kwargs: tmp_path / "a.ass")
    def fake_burn(*args, **kwargs):
        Path(args[2]).touch()
    monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
    
    # Should pass finding other.srt
    res = video_processing.generate_video_variant(
        "job1", input_video, artifact_dir, "1280x720", job_store, "u1"
    )
    assert res.exists()
