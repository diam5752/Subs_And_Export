from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from backend.app.core.config import settings
from backend.app.services import provider_clients
from backend.app.services.transcription import elevenlabs_scribe as scribe_module
from backend.app.services.transcription.elevenlabs_scribe import (
    ElevenLabsScribeTranscriber,
    delete_elevenlabs_transcript,
)


class FakeResponse:
    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


@pytest.fixture(autouse=True)
def provider_erasure_journal(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    journal = MagicMock()
    monkeypatch.setattr(
        scribe_module,
        "configured_erasure_journal",
        lambda: journal,
    )
    return journal


def test_scribe_is_fail_closed_while_feature_flag_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: A developer's enabled local Scribe flag leaked into this
    # fail-closed test and allowed the fake transport to run.
    monkeypatch.setattr(settings, "elevenlabs_enabled", False)
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
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    monkeypatch.setattr(settings, "elevenlabs_api_base", "http://app-edge:8081/elevenlabs/")
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    captured: dict[str, Any] = {}
    deleted: dict[str, Any] = {}

    def transport(*args: Any, **kwargs: Any) -> FakeResponse:
        captured["args"] = args
        captured.update(kwargs)
        return FakeResponse(
            {
                "transcription_id": "safeTranscript123",
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

    def delete_transport(*args: Any, **kwargs: Any) -> FakeResponse:
        provider_erasure_journal.append_provider_transcript.assert_called_once_with(
            provider="elevenlabs",
            transcript_id="safeTranscript123",
        )
        deleted["args"] = args
        deleted.update(kwargs)
        return FakeResponse(None)

    progress: list[float] = []
    srt_path, cues = ElevenLabsScribeTranscriber(
        api_key="test-key",
        transport=transport,
        delete_transport=delete_transport,
    ).transcribe(
        audio_path,
        tmp_path / "output",
        language="el",
        model="scribe_v2",
        progress_callback=progress.append,
    )

    assert captured["args"] == ("http://app-edge:8081/elevenlabs/v1/speech-to-text",)
    assert captured["headers"] == {"xi-api-key": "test-key"}
    assert captured["data"] == {
        "model_id": "scribe_v2",
        "language_code": "ell",
        "timestamps_granularity": "word",
        "diarize": "false",
        "tag_audio_events": "false",
    }
    assert deleted == {
        "args": ("http://app-edge:8081/elevenlabs/v1/speech-to-text/transcripts/safeTranscript123",),
        "headers": {"xi-api-key": "test-key"},
        "timeout": (5.0, 30.0),
    }
    assert len(cues) == 2
    assert [cue.text for cue in cues] == ["ΓΕΙΑ ΣΟΥ.", "ΤΙ ΚΑΝΕΙΣ;"]
    assert cues[0].words is not None
    assert [word.text for word in cues[0].words] == ["ΓΕΙΑ", "ΣΟΥ."]
    assert srt_path.exists()
    assert "ΓΕΙΑ ΣΟΥ." in srt_path.read_text(encoding="utf-8")
    assert progress == [10.0, 90.0, 100.0]


def test_scribe_accepts_memory_only_m4a_without_creating_local_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    captured: dict[str, Any] = {}

    def transport(*args: Any, **kwargs: Any) -> FakeResponse:
        captured.update(kwargs)
        return FakeResponse(
            {
                "transcription_id": "memoryOnly123",
                "words": [
                    {"text": "Γεια", "start": 0.0, "end": 0.5, "type": "word"},
                ],
            }
        )

    cues = ElevenLabsScribeTranscriber(
        api_key="test-key",
        transport=transport,
        delete_transport=lambda *args, **kwargs: FakeResponse(None),
    ).transcribe_bytes(
        b"in-memory-m4a",
        filename="../../private-name.m4a",
        content_type="audio/mp4",
    )

    upload = captured["files"]["file"]
    assert upload == ("private-name.m4a", b"in-memory-m4a", "audio/mp4")
    assert [cue.text for cue in cues] == ["ΓΕΙΑ"]
    assert list(tmp_path.iterdir()) == []
    provider_erasure_journal.append_provider_transcript.assert_called_once_with(
        provider="elevenlabs",
        transcript_id="memoryOnly123",
    )


@pytest.mark.parametrize(
    "api_base",
    (
        "",
        "ftp://api.elevenlabs.io",
        "https://user:secret@api.elevenlabs.io",
        "https://api.elevenlabs.io?redirect=1",
        "https://api.elevenlabs.io#fragment",
    ),
)
def test_scribe_rejects_invalid_api_relay_configuration(
    monkeypatch: pytest.MonkeyPatch,
    api_base: str,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_api_base", api_base)

    with pytest.raises(RuntimeError, match="relay configuration"):
        ElevenLabsScribeTranscriber._scribe_endpoint()


def test_scribe_rejects_responses_without_word_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    deleted: list[str] = []

    def delete_transport(endpoint: str, **_kwargs: Any) -> FakeResponse:
        deleted.append(endpoint)
        return FakeResponse(None)

    with pytest.raises(RuntimeError, match="word timestamps"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse({"transcription_id": "invalidWords123", "text": "Γεια"}),
            delete_transport=delete_transport,
        ).transcribe(audio_path, tmp_path / "output", language="el", model="scribe_v2")

    assert deleted == [f"{settings.elevenlabs_api_base.rstrip('/')}/v1/speech-to-text/transcripts/invalidWords123"]
    provider_erasure_journal.append_provider_transcript.assert_called_once_with(
        provider="elevenlabs",
        transcript_id="invalidWords123",
    )
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "transcription_id",
    (None, "", "../other-transcript", "contains/slash", "contains space", "a" * 129),
)
def test_scribe_fails_closed_without_a_safe_deletable_transcript_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transcription_id: str | None,
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    payload: dict[str, Any] = {"words": []}
    if transcription_id is not None:
        payload["transcription_id"] = transcription_id
    delete_transport = MagicMock()

    with pytest.raises(RuntimeError, match="deletable transcript identifier"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse(payload),
            delete_transport=delete_transport,
        ).transcribe(audio_path, tmp_path / "output")

    delete_transport.assert_not_called()
    provider_erasure_journal.append_provider_transcript.assert_not_called()
    assert not (tmp_path / "output").exists()


def test_scribe_retries_provider_deletion_then_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    delete_transport = MagicMock(side_effect=requests.Timeout("delete timeout"))
    retry_sleep = MagicMock()

    with pytest.raises(RuntimeError, match="could not delete"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse({"transcription_id": "deleteRetry123", "words": []}),
            delete_transport=delete_transport,
            retry_sleep=retry_sleep,
        ).transcribe(audio_path, tmp_path / "output")

    assert delete_transport.call_count == 3
    provider_erasure_journal.append_provider_transcript.assert_called_once_with(
        provider="elevenlabs",
        transcript_id="deleteRetry123",
    )
    assert all(call.kwargs["timeout"] == (5.0, 30.0) for call in delete_transport.call_args_list)
    assert [call.args[0] for call in retry_sleep.call_args_list] == [0.25, 0.5]
    assert not (tmp_path / "output").exists()


def test_scribe_best_effort_deletes_but_fails_without_a_durable_tombstone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    provider_erasure_journal.append_provider_transcript.side_effect = RuntimeError("journal unavailable")
    delete_transport = MagicMock(return_value=FakeResponse(None))

    with pytest.raises(RuntimeError, match="journal unavailable"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse({"transcription_id": "durableFirst123", "words": []}),
            delete_transport=delete_transport,
        ).transcribe(audio_path, tmp_path / "output")

    delete_transport.assert_called_once_with(
        f"{settings.elevenlabs_api_base.rstrip('/')}/v1/speech-to-text/transcripts/durableFirst123",
        headers={"xi-api-key": "test-key"},
        timeout=(5.0, 30.0),
    )
    assert not (tmp_path / "output").exists()


def test_scribe_reports_when_journal_and_emergency_delete_both_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_erasure_journal: MagicMock,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    provider_erasure_journal.append_provider_transcript.side_effect = RuntimeError(
        "journal unavailable",
    )
    delete_transport = MagicMock(side_effect=requests.Timeout("delete unavailable"))

    with pytest.raises(RuntimeError, match="could not be recorded or confirmed"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse(
                {"transcription_id": "untrackedDelete123", "words": []},
            ),
            delete_transport=delete_transport,
            retry_sleep=lambda _delay: None,
        ).transcribe(audio_path, tmp_path / "output")

    assert delete_transport.call_count == 3
    assert not (tmp_path / "output").exists()


def test_provider_transcript_delete_treats_not_found_as_already_erased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_api_base", "https://relay.example")
    transport = MagicMock(return_value=FakeResponse(None, status_code=404))
    retry_sleep = MagicMock()

    delete_elevenlabs_transcript(
        "alreadyDeleted123",
        api_key="test-key",
        transport=transport,
        retry_sleep=retry_sleep,
    )

    transport.assert_called_once_with(
        "https://relay.example/v1/speech-to-text/transcripts/alreadyDeleted123",
        headers={"xi-api-key": "test-key"},
        timeout=(5.0, 30.0),
    )
    retry_sleep.assert_not_called()


def test_scribe_deletes_provider_transcript_before_honouring_late_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "elevenlabs_enabled", True)
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 0.25)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    events: list[str] = []

    def check_cancelled() -> None:
        events.append("check")
        if len(events) == 3:
            raise InterruptedError("cancelled")

    def delete_transport(*_args: Any, **_kwargs: Any) -> FakeResponse:
        events.append("delete")
        return FakeResponse(None)

    with pytest.raises(InterruptedError, match="cancelled"):
        ElevenLabsScribeTranscriber(
            api_key="test-key",
            transport=lambda *args, **kwargs: FakeResponse({"transcription_id": "cancelAfterDelete123", "words": []}),
            delete_transport=delete_transport,
        ).transcribe(
            audio_path,
            tmp_path / "output",
            check_cancelled=check_cancelled,
        )

    assert events == ["check", "delete", "check"]
    assert not (tmp_path / "output").exists()


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


def test_scribe_rejects_non_object_payload_after_initial_cancellation_check(
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

    assert checks == ["checked"]


def test_resolve_elevenlabs_api_key_uses_environment_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")

    assert provider_clients.resolve_elevenlabs_api_key() == "test-elevenlabs-key"
