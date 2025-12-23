import pytest
import sys
import types
from pathlib import Path
from backend.app.services import subtitles

# 1. subtitles.py tests (Social Copy, Viral Metadata, Fact Check)

def test_subtitles_llm_timeouts(monkeypatch):
    """Verify that all LLM calls in subtitles.py enforce a timeout."""

    calls = []

    class MockCompletions:
        def create(self, *args, **kwargs):
            calls.append(kwargs)

            if "timeout" not in kwargs:
                 raise AssertionError("Missing timeout argument in OpenAI call")

            # Return valid JSON for social copy to pass validation
            return type("Resp", (), {
                "choices": [type("Choice", (), {
                    "message": type("Msg", (), {
                        "content": '{"title": "t", "description": "d", "hashtags": [], "items": [], "truth_score": 100, "supported_claims_pct": 100, "claims_checked": 0}'
                    })()
                })()]
            })()

    class MockClient:
        class chat:
            completions = MockCompletions()

    # Patch the utility function used by services
    monkeypatch.setattr("backend.app.services.llm_utils.load_openai_client", lambda k: MockClient())
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    # Test build_social_copy_llm
    print("Testing build_social_copy_llm...")
    subtitles.build_social_copy_llm("text")
    assert calls[-1]["timeout"] >= 10.0

    # Test generate_fact_check
    print("Testing generate_fact_check...")
    subtitles.generate_fact_check("text")
    assert calls[-1]["timeout"] >= 10.0


# 2. openai_cloud.py tests

def test_openai_transcribe_timeout(monkeypatch, tmp_path):
    class MockTranscriptions:
        def create(self, *args, **kwargs):
            if "timeout" not in kwargs:
                raise AssertionError("Missing timeout argument in OpenAI transcription")
            assert kwargs["timeout"] >= 60.0
            return type("Resp", (), {"text": "", "segments": []})()

    class MockClient:
        class audio:
            transcriptions = MockTranscriptions()

    # Patch the function where it's used (public name now)
    monkeypatch.setattr("backend.app.services.transcription.openai_cloud.load_openai_client", lambda k: MockClient())

    from backend.app.services.transcription.openai_cloud import OpenAITranscriber

    audio = tmp_path / "test.wav"
    audio.touch()

    print("Testing OpenAITranscriber...")
    OpenAITranscriber(api_key="k").transcribe(audio, tmp_path)


# 3. groq_cloud.py tests

def test_groq_transcribe_timeout(monkeypatch, tmp_path):
    class MockTranscriptions:
        def create(self, *args, **kwargs):
            if "timeout" not in kwargs:
                raise AssertionError("Missing timeout argument in Groq transcription")
            assert kwargs["timeout"] >= 60.0
            return type("Resp", (), {"text": "", "segments": []})()

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        class audio:
            transcriptions = MockTranscriptions()

    # Mock OpenAI import for Groq
    mock_openai = types.SimpleNamespace(OpenAI=MockClient)
    monkeypatch.setitem(sys.modules, "openai", mock_openai)

    from backend.app.services.transcription.groq_cloud import GroqTranscriber

    audio = tmp_path / "test.wav"
    audio.touch()

    print("Testing GroqTranscriber...")
    GroqTranscriber(api_key="k").transcribe(audio, tmp_path)


# 4. ffmpeg/subprocess tests

def test_ffmpeg_probe_timeout(monkeypatch):
    """Verify probe_media uses a timeout."""
    import subprocess
    from backend.app.services import ffmpeg_utils

    called_with_timeout = False

    class MockResult:
        stdout = "{}"
        returncode = 0

    def mock_run_success(*args, **kwargs):
        nonlocal called_with_timeout
        if "timeout" in kwargs and kwargs["timeout"] is not None:
            called_with_timeout = True
        return MockResult()

    monkeypatch.setattr(subprocess, "run", mock_run_success)

    ffmpeg_utils.probe_media(Path("dummy.mp4"))
    assert called_with_timeout


def test_get_video_duration_timeout(monkeypatch):
    """Verify get_video_duration uses a timeout."""
    import subprocess
    from backend.app.services import subtitles

    called_with_timeout = False

    class MockResult:
        stdout = b"10.0"
        returncode = 0

    def mock_run_success(*args, **kwargs):
        nonlocal called_with_timeout
        if "timeout" in kwargs and kwargs["timeout"] is not None:
            called_with_timeout = True
        return MockResult()

    monkeypatch.setattr(subprocess, "run", mock_run_success)

    subtitles.get_video_duration(Path("dummy.mp4"))
    assert called_with_timeout
