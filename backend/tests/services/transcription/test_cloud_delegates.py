from unittest.mock import MagicMock, patch, mock_open
import pytest
from pathlib import Path

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

        # Verify initialization (base_url for Groq)
        MockOpenAI.assert_called_with(
            api_key="fake-key",
            base_url="https://api.groq.com/openai/v1"
        )
        # Verify transcribe call
        mock_client.audio.transcriptions.create.assert_called_with(
            model="whisper-large-v3", # Default
            file=match_any_file_handle(),
            language="fr",
            prompt=None,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"]
        )

def test_groq_transcriber_missing_api_key(tmp_path):
    (tmp_path / "in.wav").touch()
    with patch("backend.app.services.transcription.groq_cloud._resolve_groq_api_key", return_value=None):
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

def test_openai_transcriber_delegates(tmp_path):
    (tmp_path / "in.wav").touch()
    mock_transcript = MagicMock()
    mock_transcript.segments = []

    with patch("backend.app.services.transcription.openai_cloud._load_openai_client") as mock_load:
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
            timestamp_granularities=["word"]
        )

class match_any_file_handle:
    def __eq__(self, other):
        return hasattr(other, "read")

