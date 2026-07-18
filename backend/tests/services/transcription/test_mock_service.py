from pathlib import Path

import pytest

from backend.app.services.transcription.mock_service import MockTranscriber


def test_mock_transcriber_builds_word_timed_srt_without_network(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"mock")
    progress: list[float] = []

    srt_path, cues = MockTranscriber().transcribe(
        audio_path,
        tmp_path / "output",
        total_duration=12.0,
        progress_callback=progress.append,
    )

    assert srt_path.exists()
    assert len(cues) == 4
    assert cues[0].start == 0.0
    assert cues[-1].end == pytest.approx(12.0)
    assert all(cue.words for cue in cues)
    assert cues[0].words[0].start == 0.0
    assert progress == [10.0, 100.0]
    subtitle_text = srt_path.read_text(encoding="utf-8")
    assert "ΔΕΙΓΜΑ ΥΠΟΤΙΤΛΩΝ" in subtitle_text
    assert "MOCK" not in subtitle_text


def test_mock_transcriber_checks_cancellation(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"mock")

    def cancel() -> None:
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError, match="cancelled"):
        MockTranscriber().transcribe(audio_path, tmp_path / "output", check_cancelled=cancel)
