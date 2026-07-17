from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from backend.app.core.config import settings
from backend.app.services import llm_utils
from backend.app.services.transcription.elevenlabs_scribe import ElevenLabsScribeTranscriber


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


def test_scribe_is_fail_closed_while_feature_flag_is_disabled(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    transport_called = False

    def transport(*args: Any, **kwargs: Any) -> FakeResponse:
        nonlocal transport_called
        transport_called = True
        return FakeResponse({})

    with pytest.raises(RuntimeError, match="disabled"):
        ElevenLabsScribeTranscriber(api_key="test-key", transport=transport).transcribe(
            audio_path,
            tmp_path / "output",
            language="el",
            model="scribe_v2",
        )

    assert transport_called is False


def test_scribe_parses_word_timestamps_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    captured: dict[str, Any] = {}

    def transport(*args: Any, **kwargs: Any) -> FakeResponse:
        captured.update(kwargs)
        return FakeResponse(
            {
                "text": "Γεια σου. Τι κάνεις;",
                "words": [
                    {"text": "Γεια", "start": 0.0, "end": 0.4, "type": "word"},
                    {"text": " ", "start": 0.4, "end": 0.45, "type": "spacing"},
                    {"text": "σου.", "start": 0.45, "end": 0.9, "type": "word"},
                    {"text": "Τι", "start": 1.1, "end": 1.3, "type": "word"},
                    {"text": "κάνεις;", "start": 1.3, "end": 1.8, "type": "word"},
                ],
            }
        )

    progress: list[float] = []
    srt_path, cues = ElevenLabsScribeTranscriber(
        api_key="test-key",
        transport=transport,
    ).transcribe(
        audio_path,
        tmp_path / "output",
        language="el",
        model="scribe_v2",
        progress_callback=progress.append,
    )

    assert captured["headers"] == {"xi-api-key": "test-key"}
    assert captured["data"] == {
        "model_id": "scribe_v2",
        "language_code": "ell",
        "timestamps_granularity": "word",
        "diarize": "false",
        "tag_audio_events": "false",
    }
    assert len(cues) == 2
    assert [cue.text for cue in cues] == ["ΓΕΙΑ ΣΟΥ.", "ΤΙ ΚΑΝΕΙΣ;"]
    assert cues[0].words is not None
    assert [word.text for word in cues[0].words] == ["ΓΕΙΑ", "ΣΟΥ."]
    assert srt_path.exists()
    assert "ΓΕΙΑ ΣΟΥ." in srt_path.read_text(encoding="utf-8")
    assert progress == [10.0, 90.0, 100.0]


def test_scribe_rejects_responses_without_word_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")

    with pytest.raises(RuntimeError, match="word timestamps"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse({"text": "Γεια"}),
        ).transcribe(audio_path, tmp_path / "output", language="el", model="scribe_v2")


def test_scribe_filters_invalid_words_and_handles_auto_language() -> None:
    assert ElevenLabsScribeTranscriber._language_code("auto") is None
    assert ElevenLabsScribeTranscriber._language_code("fra") == "fra"

    words = ElevenLabsScribeTranscriber._parse_words(
        {
            "words": [
                "invalid",
                {"type": "spacing", "text": " ", "start": 0.0, "end": 0.1},
                {"type": "word", "text": " ", "start": 0.0, "end": 0.1},
                {"type": "word", "text": "χωρίς", "start": None, "end": 0.2},
                {"type": "word", "text": "λάθος", "start": 0.4, "end": 0.2},
                {"type": "word", "text": "σωστό", "start": 0.5, "end": 0.9},
            ]
        }
    )

    assert [(word.start, word.end, word.text) for word in words] == [(0.5, 0.9, "ΣΩΣΤΟ")]


def test_scribe_rejects_each_closed_safety_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    transcriber = ElevenLabsScribeTranscriber(api_key=None, transport=lambda *args, **kwargs: FakeResponse({}))

    with pytest.raises(ValueError, match="scribe_v2"):
        transcriber.transcribe(audio_path, tmp_path, model="another-model")

    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", True)
    with pytest.raises(RuntimeError, match="mock mode"):
        transcriber.transcribe(audio_path, tmp_path)

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 0.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.0)
    with pytest.raises(RuntimeError, match="budgets"):
        transcriber.transcribe(audio_path, tmp_path)

    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    monkeypatch.setattr(
        "backend.app.services.transcription.elevenlabs_scribe.resolve_elevenlabs_api_key",
        lambda: None,
    )
    with pytest.raises(RuntimeError, match="API key"):
        transcriber.transcribe(audio_path, tmp_path)


def test_scribe_wraps_transport_failures_without_a_real_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")

    def timeout(*args: Any, **kwargs: Any) -> FakeResponse:
        raise requests.Timeout("timed out")

    with pytest.raises(RuntimeError, match="transcription failed"):
        ElevenLabsScribeTranscriber(api_key="test-key", transport=timeout).transcribe(
            audio_path,
            tmp_path / "output",
        )


def test_scribe_rejects_non_object_payload_and_checks_cancellation_twice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    checks: list[str] = []

    with pytest.raises(RuntimeError, match="invalid response"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse([]),
        ).transcribe(
            audio_path,
            tmp_path / "output",
            language="auto",
            check_cancelled=lambda: checks.append("checked"),
        )

    assert checks == ["checked", "checked"]


def test_resolve_elevenlabs_api_key_uses_environment_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")

    assert llm_utils.resolve_elevenlabs_api_key() == "test-elevenlabs-key"
