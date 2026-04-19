from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.services.transcription.local_whisper import LocalWhisperTranscriber


def test_local_whisper_transcriber_uses_large_v3_turbo_alias(tmp_path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")

    segment = SimpleNamespace(
        start=0.0,
        end=1.2,
        text=" Hello world ",
        words=[
            SimpleNamespace(start=0.0, end=0.5, word=" Hello"),
            SimpleNamespace(start=0.5, end=1.2, word=" world "),
        ],
    )
    model_instance = MagicMock()
    model_instance.transcribe.return_value = (iter([segment]), SimpleNamespace(language="el"))
    faster_whisper_module = SimpleNamespace(WhisperModel=MagicMock(return_value=model_instance))

    with (
        patch("backend.app.services.transcription.local_whisper._load_faster_whisper", return_value=faster_whisper_module),
        patch("backend.app.services.transcription.local_whisper.os.cpu_count", return_value=16),
    ):
        transcriber = LocalWhisperTranscriber(device="cpu", compute_type="auto", beam_size=7)
        srt_path, cues = transcriber.transcribe(
            audio_path,
            tmp_path,
            language="el",
            model="whisper-large-v3-turbo",
            progress_callback=MagicMock(),
            initial_prompt="brand words",
        )

    faster_whisper_module.WhisperModel.assert_called_once_with(
        model_size_or_path="large-v3-turbo",
        device="cpu",
        compute_type="int8",
        cpu_threads=8,
    )
    model_instance.transcribe.assert_called_once()
    kwargs = model_instance.transcribe.call_args.kwargs
    assert kwargs["beam_size"] == 7
    assert kwargs["vad_filter"] is True
    assert kwargs["initial_prompt"] == "brand words"
    assert srt_path.exists()
    assert cues[0].text.strip() == "HELLO WORLD"
    assert cues[0].words is not None
    assert [word.text for word in cues[0].words] == ["HELLO", "WORLD"]


def test_local_whisper_transcriber_checks_cancellation_while_iterating_segments(tmp_path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")

    first_segment = SimpleNamespace(start=0.0, end=1.0, text="One", words=None)
    second_segment = SimpleNamespace(start=1.0, end=2.0, text="Two", words=None)
    model_instance = MagicMock()
    model_instance.transcribe.return_value = (iter([first_segment, second_segment]), SimpleNamespace(language="el"))
    faster_whisper_module = SimpleNamespace(WhisperModel=MagicMock(return_value=model_instance))

    checks = {"count": 0}

    def check_cancelled() -> None:
        checks["count"] += 1
        # REGRESSION: cancellation must stop local transcription mid-stream instead of
        # waiting for the whole transcript loop to finish.
        if checks["count"] >= 3:
            raise RuntimeError("cancelled")

    with patch("backend.app.services.transcription.local_whisper._load_faster_whisper", return_value=faster_whisper_module):
        transcriber = LocalWhisperTranscriber(device="cpu", compute_type="auto")

        try:
            transcriber.transcribe(audio_path, tmp_path, check_cancelled=check_cancelled)
        except RuntimeError as exc:
            assert "cancelled" in str(exc)
        else:
            raise AssertionError("expected cancellation to abort transcription")
