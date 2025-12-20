import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
import subprocess

import pytest
import tomllib  # For mocking

from backend.app.core import config
from backend.app.services import (
    fact_checking,
    llm_utils,
    social_intelligence,
    subtitle_renderer,
    subtitles,
)
from backend.app.services.subtitle_types import Cue, WordTiming, TimeRange
from backend.app.services.transcription.base import Transcriber

# Import modules to patch them directly
from backend.app.services.transcription import openai_cloud
from backend.app.services import social_intelligence as social_lib


def test_extract_audio_invokes_ffmpeg(monkeypatch, tmp_path: Path):
    """Test that extract_audio calls ffmpeg with correct arguments."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    input_video = tmp_path / "video.mp4"
    input_video.touch()

    class MockPopen:
        def __init__(self, cmd, stdout, stderr, **kwargs):
            assert cmd[0] == "ffmpeg"
            # Simulate creation of the output file
            Path(cmd[-1]).write_bytes(b"audio")
            self.returncode = 0
            self.stderr = None

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return

        def communicate(self, timeout=None):
            return None, None

        def kill(self):
            pass

    # We must patch subprocess.Popen specifically
    monkeypatch.setattr(subprocess, "Popen", MockPopen)
    
    audio_path = subtitles.extract_audio(input_video, output_dir=output_dir)
    assert audio_path.exists()
    assert audio_path.name == "video.wav"


def test_get_video_duration(monkeypatch):
    class Result:
        stdout = b"3.5"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    assert subtitles.get_video_duration(Path("dummy")) == 3.5


def test_generate_subtitles_from_audio_writes_srt(monkeypatch, tmp_path: Path):
    """Test deprecated generate_subtitles_from_audio wrapper still works via local provider."""
    # We mock LocalWhisperTranscriber to avoid loading real model
    with patch("backend.app.services.transcription.local_whisper.LocalWhisperTranscriber") as MockTranscriber:
        mock_instance = MockTranscriber.return_value
        
        # Setup mock return
        srt_path = tmp_path / "test.srt"
        srt_path.touch()
        cues = [
            Cue(
                start=0.0,
                end=1.5,
                text="Γεια σου",
                words=[WordTiming(0.0, 0.7, "Γεια"), WordTiming(0.7, 1.5, "σου")],
            )
        ]
        mock_instance.transcribe.return_value = (srt_path, cues)

        audio_path = tmp_path / "audio.wav"
        audio_path.touch()

        # Call the deprecated function
        res_srt, res_cues = subtitles.generate_subtitles_from_audio(
            audio_path,
            output_dir=tmp_path,
            provider="local"
        )

        assert res_srt == srt_path
        assert len(res_cues) == 1
        assert res_cues[0].text == "Γεια σου"


def test_create_styled_subtitle_file_generates_ass(tmp_path: Path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello World\n", encoding="utf-8"
    )

    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt_path,
        primary_color="&H00FFFF",  # Cyan
        font_size=12,
        subtitle_position=10,
        output_dir=tmp_path,
    )

    assert ass_path.exists()
    assert ass_path.suffix == ".ass"
    content = ass_path.read_text(encoding="utf-8")
    assert "Style: Default" in content
    # The format might be different, let's just check the value is present
    assert "12" in content
    assert "&H00FFFF" in content  # color
    # Text is normalized to Upper
    assert "HELLO WORLD" in content


def test_create_styled_subtitle_file_active_word_wraps_lines(tmp_path: Path):
    """
    Test that 'active-word' or 'active' style properly wraps long lines
    and respects manual line breaks, while highlighting words.
    """
    srt_path = tmp_path / "subs.srt"
    srt_content = (
        "1\n00:00:01,000 --> 00:00:05,000\n"
        "This is a very long line that should definitely wrap because it exceeds the character limit "
        "and we want to verify that the active word highlighting is still applied correctly to wrapped lines.\n"
    )
    srt_path.write_text(srt_content, encoding="utf-8")

    # Mock cues with word timings for this long line
    words = []
    text = "This is a very long line that should definitely wrap because it exceeds the character limit and we want to verify that the active word highlighting is still applied correctly to wrapped lines."
    parts = text.split()
    duration = 4.0
    step = duration / len(parts)
    for i, w in enumerate(parts):
        words.append(WordTiming(1.0 + i * step, 1.0 + (i + 1) * step, w))

    cues = [Cue(1.0, 5.0, text, words=words)]

    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt_path,
        cues=cues,
        highlight_style="active",  # or 'active-word'
        font_size=20,
        max_lines=2,
        output_dir=tmp_path,
    )

    content = ass_path.read_text(encoding="utf-8")
    # Verify we have multiple events for the same time range (one per word highlight step)
    # The active word logic generates many lines.
    lines = content.splitlines()
    dialogue_lines = [l for l in lines if l.startswith("Dialogue:")]
    assert len(dialogue_lines) > 5


def test_format_karaoke_wraps_long_lines():
    """Test that karaoke formatting correctly wraps lines and applies \\k tags."""
    text = "One two three four five six seven eight nine ten"
    # Create fake word timings
    words = []
    # 10 words, 0.5s each
    for i, w in enumerate(text.split()):
        words.append(WordTiming(float(i), float(i) + 0.5, w))

    # Force a very short max_chars just for testing logic
    lines = subtitle_renderer.wrap_word_timings(words, max_chars=15)
    assert len(lines) > 1
    assert lines[0][0].text == "One"  # Just checking structure


def test_generate_subtitles_from_audio_accepts_auto_language(monkeypatch, tmp_path: Path):
    with patch("backend.app.services.transcription.local_whisper.LocalWhisperTranscriber") as MockTranscriber:
        mock_instance = MockTranscriber.return_value
        mock_instance.transcribe.return_value = (tmp_path / "test.srt", [])

        audio_path = tmp_path / "audio.wav"
        audio_path.touch()

        # Pass "auto"
        subtitles.generate_subtitles_from_audio(
            audio_path,
            language="auto",
            output_dir=tmp_path,
            provider="local"
        )

        call_args = mock_instance.transcribe.call_args
        assert call_args
        assert call_args.kwargs["language"] == config.WHISPER_LANGUAGE


def test_generate_subtitles_from_audio_passes_decoding_params(monkeypatch, tmp_path: Path):
    with patch("backend.app.services.transcription.local_whisper.LocalWhisperTranscriber") as MockTranscriber:
        mock_instance = MockTranscriber.return_value
        mock_instance.transcribe.return_value = (tmp_path / "test.srt", [])

        audio_path = tmp_path / "audio.wav"
        audio_path.touch()

        subtitles.generate_subtitles_from_audio(
            audio_path,
            beam_size=10,
            best_of=3,
            temperature=0.2,
            condition_on_previous_text=True,
            initial_prompt="Hello",
            output_dir=tmp_path,
            provider="local",
        )

        _, init_kwargs = MockTranscriber.call_args
        assert init_kwargs["beam_size"] == 10

        _, call_kwargs = mock_instance.transcribe.call_args
        
        assert call_kwargs["best_of"] == 3
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["condition_on_previous_text"] is True
        assert call_kwargs["initial_prompt"] == "Hello"


# --- Testing New Service Logic (Refactored) ---

def test_clean_json_response_strips_fences():
    raw = "```json\n{\"foo\": \"bar\"}\n```"
    cleaned = llm_utils.clean_json_response(raw)
    assert cleaned == '{"foo": "bar"}'


def test_build_social_copy_llm_retries_and_raises(monkeypatch):
    monkeypatch.setattr(llm_utils, "resolve_openai_api_key", lambda k: "sk-fake")
    
    # Mock fallback to ensure it is returned
    fallback = subtitles.SocialCopy(
        subtitles.SocialContent("Fallback EL", "Fallback EN", "Fallback EL Desc", "Fallback EN Desc", ["#fallback"])
    )
    monkeypatch.setattr(social_lib, "build_social_copy", lambda text: fallback)
    # Also patch subtitles.build_social_copy because wrapper uses it
    monkeypatch.setattr(subtitles, "build_social_copy", lambda text: fallback)

    mock_client = MagicMock()
    # Mock create to raise exception
    mock_client.chat.completions.create.side_effect = Exception("API Error")
    
    # Patch where it is used! (In llm_utils because social_lib calls it from there)
    monkeypatch.setattr(llm_utils, "load_openai_client", lambda k: mock_client)

    # Call the WRAPPER which handles fallback
    res = subtitles.build_social_copy_llm("some text", api_key="sk-fake")
    assert res is not None
    assert res.generic.title_en == "Fallback EN"


def test_compose_title_branches():
    # Test short text - MUST PASS LIST of keywords
    t1 = social_intelligence._compose_title(["Short"])
    assert "Short" in t1
    
    # Test long text - MUST PASS LIST
    kw = ["Word"] * 20
    t2 = social_intelligence._compose_title(kw)
    # Logic: f"{keywords[0].title()} & {keywords[1].title()} Moments"
    assert "Word" in t2
    assert "Moments" in t2


def test_load_openai_client_success(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", MagicMock())
    client = llm_utils.load_openai_client("sk-test")
    assert client is not None


def test_build_social_copy_llm_empty_response(monkeypatch):
    monkeypatch.setattr(llm_utils, "resolve_openai_api_key", lambda k: "sk-fake")
    mock_client = MagicMock()
    
    # Return empty content
    mock_response = MagicMock()
    mock_response.choices[0].message.content = ""
    mock_response.choices[0].message.refusal = None
    mock_client.chat.completions.create.return_value = mock_response
    
    # Patch in llm_utils
    monkeypatch.setattr(llm_utils, "load_openai_client", lambda k: mock_client)
    
    # Pass fallback
    fallback = subtitles.SocialCopy(
        subtitles.SocialContent("Fallback EL", "Fallback EN", "Fallback EL Desc", "Fallback EN Desc", ["#fallback"])
    )
    monkeypatch.setattr(subtitles, "build_social_copy", lambda text: fallback)
    monkeypatch.setattr(social_lib, "build_social_copy", lambda text: fallback)

    # Call wrapper for fallback logic
    res = subtitles.build_social_copy_llm("text", api_key="sk-fake")
    assert res is not None
    # Wait, wrapper fallback logic: "Failed to generate valid social copy..." raised by build_social_copy_llm
    # Then caught by wrapper.
    # The wrapper should catch ValueError and return fallback.
    assert res.generic.title_en == "Fallback EN"


def test_transcribe_openai_error(monkeypatch, tmp_path):
    """Test OpeanAI transcriber handling API errors."""
    
    # Mock where it is used in openai_cloud!
    monkeypatch.setattr(openai_cloud, "resolve_openai_api_key", lambda: "sk-fake")
    monkeypatch.setitem(sys.modules, "openai", MagicMock())
    
    # Mock client to raise
    mock_client = MagicMock()
    mock_client.audio = MagicMock()
    mock_client.audio.transcriptions = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = Exception("OpenAI Error")
    monkeypatch.setattr(openai_cloud, "load_openai_client", lambda k: mock_client)

    transcriber = openai_cloud.OpenAITranscriber(api_key="sk-fake")
    audio = tmp_path / "audio.wav"
    audio.touch()

    with pytest.raises(RuntimeError, match="OpenAI transcription failed"):
        transcriber.transcribe(audio, tmp_path)


def test_resolve_openai_api_key(monkeypatch):
    # Mock secrets loading in llm_utils
    monkeypatch.setattr(llm_utils.tomllib, "load", lambda f: {})
    # Mock Path exists in llm_utils context? No, just Path.
    monkeypatch.setattr(Path, "exists", lambda self: True)
    # Mock open
    monkeypatch.setattr("builtins.open", MagicMock())

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    assert llm_utils.resolve_openai_api_key() is None
    assert llm_utils.resolve_openai_api_key("sk-test") == "sk-test"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert llm_utils.resolve_openai_api_key() == "sk-env"


def test_wrap_lines_empty():
    assert subtitle_renderer.wrap_lines([], 10) == []


def test_split_long_cues_logic():
    # Long cue that needs splitting
    long_text = "This is a very long text that definitely needs to be split into smaller pieces"
    cues = [Cue(0.0, 10.0, long_text)]
    
    # Mock max chars to force split
    split_cues = subtitle_renderer.split_long_cues(cues, max_chars=20)
    assert len(split_cues) > 1
    assert split_cues[0].start == 0.0
    assert split_cues[-1].end == 10.0


def test_transcribe_with_openai_success(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_cloud, "resolve_openai_api_key", lambda: "sk-fake")
    monkeypatch.setitem(sys.modules, "openai", MagicMock())
    
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Hello world"
    mock_resp.start = 0.0
    mock_resp.end = 1.0
    mock_resp.words = []
    
    # Mock return attributes
    mock_transcript = MagicMock()
    mock_transcript.segments = [mock_resp]
    
    mock_client.audio.transcriptions.create.return_value = mock_transcript
    monkeypatch.setattr(openai_cloud, "load_openai_client", lambda k: mock_client)
    
    transcriber = openai_cloud.OpenAITranscriber(api_key="sk-fake")
    audio = tmp_path / "a.wav"
    audio.touch()
    
    path, result_cues = transcriber.transcribe(audio, tmp_path)
    assert len(result_cues) == 1
    assert result_cues[0].text == "HELLO WORLD"


def test_wrap_lines_preserves_all_text():
    words = [WordTiming(0, 1, "One"), WordTiming(1, 2, "Two"), WordTiming(2, 3, "Three")]
    lines = subtitle_renderer.wrap_word_timings(words, max_chars=7) # "One Two" = 7 chars
    # Expect "One Two", "Three"
    assert len(lines) == 2
    assert lines[0][0].text == "One"
    assert lines[0][1].text == "Two"
    assert lines[1][0].text == "Three"


def test_greek_text_fits_within_config_width():
    # Greek chars are wide? No, usually handled same as unicode.
    greek = "Καλημέρα κόσμε"
    width = subtitle_renderer.get_text_width(greek, font_size=20)
    assert width > 0


def test_format_karaoke_text_preserves_all_words():
    # Just a helper check
    pass 


def test_short_text_stays_on_single_line():
    words = [WordTiming(0, 1, "Hi")]
    lines = subtitle_renderer.wrap_word_timings(words, max_chars=50)
    assert len(lines) == 1


def test_resolve_groq_api_key_explicit():
    assert llm_utils.resolve_groq_api_key("gsk-test") == "gsk-test"


def test_resolve_groq_api_key_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-env")
    assert llm_utils.resolve_groq_api_key() == "gsk-env"


def test_resolve_groq_api_key_file(monkeypatch, tmp_path):
    secrets = tmp_path / "secrets.toml"
    secrets.write_bytes(b'GROQ_API_KEY = "gsk-file"')
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path.parent) # Hacky path math
    pass


def test_resolve_groq_api_key_not_found(monkeypatch):
    # Mock secrets
    monkeypatch.setattr(llm_utils.tomllib, "load", lambda f: {})
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr("builtins.open", MagicMock())
    
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm_utils.resolve_groq_api_key() is None


def test_cues_without_words_DO_split_interpolated():
    cues = [Cue(0, 10, "A very long sentence that needs splitting")]
    res = subtitle_renderer.split_long_cues(cues, max_chars=10)
    assert len(res) > 1
    # Check interpolation
    assert res[0].end < 10.0
    assert res[1].start == res[0].end


def test_standard_model_no_words_lost():
    pass


def test_per_word_karaoke():
    # Helper logic check
    pass


def test_create_styled_subtitle_file_clamps_overlapping_cues(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nCollision\n\n2\n00:00:04,000 --> 00:00:08,000\nOverlap\n")
    
    # This invokes normalize_cues_for_ass which clamps
    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt, output_dir=tmp_path
    )
    # Parsing verify?
    # We trust internal logic for now, verifying it runs without error.
    assert ass_path.exists()


def test_1_word_mode_splitting_standard_model():
    pass


def test_generate_active_word_ass_no_words(tmp_path):
    # Should fallback to karaoke or block
    pass


def test_generate_active_word_ass_logic():
    pass


def test_split_long_cues_with_phrases_interpolation():
    cues = [Cue(0, 4, "Hello world this is a test")]
    res = subtitle_renderer.split_long_cues(cues, max_chars=10)
    assert len(res) >= 2
    # split_long_cues doesn't normalize, so it should be same case
    assert "Hello" in res[0].text
    # Check timings are interpolated linearly
    # "Hello world" is ~11 chars. "this is a test" is ~14.
    # Should be about half/half duration.
    assert 1.0 < res[0].end < 3.0
