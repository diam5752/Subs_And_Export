from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.transcription.groq_cloud import GroqTranscriber
from backend.app.services.transcription.openai_cloud import OpenAITranscriber


def test_groq_transcriber_delegates(tmp_path):
    (tmp_path / "in.wav").touch()
    # Mock the response from client.audio.transcriptions.create
    mock_transcript = MagicMock()
    # Ensure it has 'segments', 'words', etc if needed, or at least doesn't crash
    mock_transcript.segments = []

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        t = GroqTranscriber(api_key="fake-key")
        t.transcribe(tmp_path / "in.wav", tmp_path, language="fr")

        # Verify initialization (base_url for Groq, with timeout)
        MockOpenAI.assert_called_with(
            api_key="fake-key",
            base_url="https://api.groq.com/openai/v1",
            timeout=60.0
        )
        # Verify transcribe call
        mock_client.audio.transcriptions.create.assert_called_with(
            model="whisper-large-v3", # Default
            file=match_any_file_handle(),
            language="fr",
            prompt=None,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            timeout=300.0,
        )

def test_groq_transcriber_missing_api_key(tmp_path):
    (tmp_path / "in.wav").touch()
    with patch("backend.app.services.transcription.groq_cloud.resolve_groq_api_key", return_value=None):
        t = GroqTranscriber(api_key=None)
        with pytest.raises(RuntimeError, match="Groq API key is required"):
            t.transcribe(tmp_path / "in.wav", tmp_path)

def test_groq_transcriber_cancellation(tmp_path):
    (tmp_path / "in.wav").touch()
    check_cancelled = MagicMock(side_effect=RuntimeError("Cancelled"))

    t = GroqTranscriber(api_key="k")
    with pytest.raises(RuntimeError, match="Cancelled"):
        t.transcribe(tmp_path / "in.wav", tmp_path, check_cancelled=check_cancelled)

    # Verify it was called before API call
    assert check_cancelled.call_count >= 1

def test_groq_transcriber_progress(tmp_path):
    (tmp_path / "in.wav").touch()
    progress_callback = MagicMock()
    mock_transcript = MagicMock()
    mock_transcript.segments = []

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        t = GroqTranscriber(api_key="k")
        t.transcribe(tmp_path / "in.wav", tmp_path, progress_callback=progress_callback)

        # Should be called with 10.0, 90.0, 100.0
        progress_callback.assert_any_call(10.0)
        progress_callback.assert_any_call(90.0)
        progress_callback.assert_any_call(100.0)


def test_groq_transcriber_wraps_api_failures(tmp_path):
    (tmp_path / "in.wav").touch()

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_client.audio.transcriptions.create.side_effect = RuntimeError("upstream boom")

        t = GroqTranscriber(api_key="k")
        with pytest.raises(RuntimeError, match="Groq transcription failed: upstream boom"):
            t.transcribe(tmp_path / "in.wav", tmp_path)


def test_groq_transcriber_builds_cues_and_writes_srt(tmp_path):
    audio_path = tmp_path / "in.wav"
    audio_path.touch()
    progress_callback = MagicMock()
    check_cancelled = MagicMock()

    segment = MagicMock()
    segment.text = " Hello world "
    segment.start = 1.0
    segment.end = 2.5
    word = MagicMock()
    word.start = 1.1
    word.end = 1.9
    word.word = " Hello "
    mock_transcript = MagicMock()
    mock_transcript.segments = [segment]
    mock_transcript.words = [word]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MockOpenAI.return_value
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        t = GroqTranscriber(api_key="k")
        srt_path, cues = t.transcribe(
            audio_path,
            tmp_path,
            progress_callback=progress_callback,
            check_cancelled=check_cancelled,
        )

    assert check_cancelled.call_count == 3
    assert srt_path.exists()
    assert "Hello world" in srt_path.read_text(encoding="utf-8")
    assert len(cues) == 1
    assert cues[0].text == " HELLO WORLD "
    assert cues[0].words[0].text == " HELLO "


class match_any_file_handle:
    def __eq__(self, other):
        return hasattr(other, "read")


def test_openai_transcriber_delegates(tmp_path):
    (tmp_path / "in.wav").touch()
    mock_transcript = MagicMock()
    mock_transcript.segments = []

    with patch("backend.app.services.transcription.openai_cloud.load_openai_client") as mock_load:
        mock_client = MagicMock()
        mock_load.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        t = OpenAITranscriber(api_key="k")
        t.transcribe(tmp_path / "in.wav", tmp_path, language="de")

        mock_load.assert_called_with("k")

        mock_client.audio.transcriptions.create.assert_called_with(
            model="whisper-1",
            file=match_any_file_handle(),
            language="de",
            prompt=None,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            timeout=300.0,
        )


def test_openai_transcriber_rejects_models_without_word_timestamps(tmp_path):
    audio_path = tmp_path / "in.wav"
    audio_path.touch()

    with pytest.raises(ValueError, match="requires whisper-1"):
        OpenAITranscriber(api_key="unused").transcribe(
            audio_path,
            tmp_path,
            model="gpt-4o-transcribe",
        )
