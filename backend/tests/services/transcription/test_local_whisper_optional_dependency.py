import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def test_subtitle_helpers_import_without_local_whisper_dependency():
    """
    REGRESSION: the FastAPI app imports `subtitles.py` at startup, so missing
    local Whisper dependencies must not crash the whole backend before any local
    transcription path is requested.
    """
    with patch.dict(sys.modules, {"faster_whisper": None}):
        module = importlib.import_module("backend.app.services.subtitles")
        reloaded = importlib.reload(module)
        assert callable(reloaded.write_srt_from_segments)


def test_local_whisper_transcriber_raises_clear_error_when_dependency_missing(tmp_path: Path):
    with patch.dict(sys.modules, {"faster_whisper": None}):
        module = importlib.import_module("backend.app.services.transcription.local_whisper")
        local_whisper = importlib.reload(module)

        transcriber = local_whisper.LocalWhisperTranscriber()

        with pytest.raises(RuntimeError, match="faster-whisper is required for local transcription"):
            transcriber.transcribe(tmp_path / "audio.wav", tmp_path)
