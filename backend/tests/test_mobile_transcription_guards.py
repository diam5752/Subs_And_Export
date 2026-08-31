from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.core.media_capacity import MediaExtractionCapacityTimeoutError
from backend.app.services.ffmpeg_utils import MediaProbe


def _headers(auth: dict[str, str], *, key: str) -> dict[str, str]:
    return {
        **auth,
        "Content-Type": "audio/mp4",
        "Idempotency-Key": key,
        "X-Gsubs-Authorized-Credits": "30",
    }


def test_mobile_replay_validates_body_but_precedes_credit_and_live_provider_gates(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint
    from backend.app.services import mobile_transcriptions as service
    from backend.app.services.points import PointsStore

    key = "mobile-replay-provider-closed"
    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )
    first = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers, key=key),
        content=b"first-bounded-audio",
    )
    assert first.status_code == 200, first.text

    probe = MagicMock(return_value=MediaProbe(duration_s=10.0, audio_codec="aac"))
    provider_gate = MagicMock(side_effect=AssertionError("provider gate must not run"))
    credit_gate = MagicMock(side_effect=AssertionError("credit gate must not run"))
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(endpoint, "probe_media_bytes", probe)
    monkeypatch.setattr(service, "resolve_mobile_transcription_engine", provider_gate)
    monkeypatch.setattr(PointsStore, "assert_can_spend", credit_gate)
    replay = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers, key=key),
        content=b"first-bounded-audio",
    )

    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    probe.assert_called_once_with(b"first-bounded-audio")
    provider_gate.assert_not_called()
    credit_gate.assert_not_called()


@pytest.mark.parametrize(
    ("case", "second_body", "second_duration", "authorized_credits"),
    [
        ("audio", b"different-bounded-audio", 10.0, "30"),
        ("duration", b"first-bounded-audio", 11.0, "30"),
        ("authorization", b"first-bounded-audio", 10.0, "60"),
    ],
)
def test_mobile_replay_rejects_idempotency_key_reuse_for_a_different_request(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    second_body: bytes,
    second_duration: float,
    authorized_credits: str,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint
    from backend.app.core.database import Database
    from backend.app.services import mobile_transcriptions as service
    from backend.app.services.jobs import JobStore
    from backend.app.services.points import PointsStore

    key = f"mobile-replay-conflict-{case}"
    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )
    first = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers, key=key),
        content=b"first-bounded-audio",
    )
    assert first.status_code == 200, first.text

    user = client.get("/auth/me", headers=funded_user_auth_headers)
    assert user.status_code == 200
    user_id = str(user.json()["id"])
    points = PointsStore(Database())
    balance_after_first = points.get_balance(user_id)
    dispatch = MagicMock(side_effect=AssertionError("conflicting replay must not dispatch"))
    monkeypatch.setattr(service, "_dispatch_audio", dispatch)
    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=second_duration, audio_codec="aac"),
    )
    headers = _headers(funded_user_auth_headers, key=key)
    headers["X-Gsubs-Authorized-Credits"] = authorized_credits

    replay = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=second_body,
    )

    assert replay.status_code == 409
    assert replay.json() == {"detail": "Idempotency key conflict"}
    dispatch.assert_not_called()
    assert points.get_balance(user_id) == balance_after_first
    assert len(JobStore(Database()).list_jobs_for_user(user_id)) == 1


def test_zero_credit_mobile_request_is_rejected_before_body_read_or_probe(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    body_reader = AsyncMock(side_effect=AssertionError("body must not be read"))
    probe = MagicMock(side_effect=AssertionError("audio must not be probed"))
    monkeypatch.setattr(endpoint, "_read_audio_body", body_reader)
    monkeypatch.setattr(endpoint, "probe_media_bytes", probe)

    response = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(user_auth_headers, key="mobile-no-credit-guard"),
        content=b"must-not-be-consumed",
    )

    assert response.status_code == 402
    assert response.json() == {"detail": "Insufficient points"}
    body_reader.assert_not_awaited()
    probe.assert_not_called()


@pytest.mark.parametrize(
    ("probe", "detail"),
    [
        (MediaProbe(duration_s=None, audio_codec="aac"), "Could not determine audio duration"),
        (MediaProbe(duration_s=float("nan"), audio_codec="aac"), "Could not determine audio duration"),
        (MediaProbe(duration_s=0.0, audio_codec="aac"), "Could not determine audio duration"),
        (MediaProbe(duration_s=10.0, audio_codec="mp3"), "Mobile audio must use AAC"),
    ],
)
def test_mobile_request_rejects_invalid_authoritative_probe(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    probe: MediaProbe,
    detail: str,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    monkeypatch.setattr(endpoint, "probe_media_bytes", lambda _body: probe)
    response = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers, key="mobile-invalid-probe"),
        content=b"bounded-audio",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    ("header", "value", "detail"),
    [
        ("Idempotency-Key", "short", "Invalid Idempotency-Key header"),
        (
            "X-Gsubs-Authorized-Credits",
            "not-a-number",
            "Invalid x-gsubs-authorized-credits header",
        ),
        (
            "X-Gsubs-Authorized-Credits",
            "030",
            "Invalid x-gsubs-authorized-credits header",
        ),
        (
            "X-Gsubs-Authorized-Credits",
            "0",
            "Invalid x-gsubs-authorized-credits header",
        ),
    ],
)
def test_mobile_request_rejects_noncanonical_headers_before_probe(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    header: str,
    value: str,
    detail: str,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    probe = MagicMock(side_effect=AssertionError("metadata must precede probing"))
    monkeypatch.setattr(endpoint, "probe_media_bytes", probe)
    headers = _headers(funded_user_auth_headers, key="mobile-metadata-guard")
    headers[header] = value
    response = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=b"bounded-audio",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": detail}
    probe.assert_not_called()


def test_mobile_probe_capacity_timeout_is_retryable(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    @contextmanager
    def unavailable_probe_slot(**_kwargs):
        raise MediaExtractionCapacityTimeoutError("busy")
        yield ()

    monkeypatch.setattr(endpoint, "lock_audio_extraction", unavailable_probe_slot)
    response = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers, key="mobile-probe-capacity"),
        content=b"bounded-audio",
    )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "Audio validation capacity is temporarily busy",
    }


def test_mobile_request_rejects_oversized_declared_body_before_reading(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    body_reader = AsyncMock(side_effect=AssertionError("body must not be read"))
    monkeypatch.setattr(endpoint, "_read_audio_body", body_reader)
    headers = _headers(funded_user_auth_headers, key="mobile-oversized-length")
    headers["Content-Length"] = str(endpoint.MOBILE_AUDIO_MAX_BYTES + 1)

    response = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=b"bounded-audio",
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Mobile audio is too large"}
    body_reader.assert_not_awaited()


def test_mobile_request_rejects_body_shorter_than_declared_length(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
) -> None:
    headers = _headers(funded_user_auth_headers, key="mobile-incomplete-body")
    headers["Content-Length"] = "100"

    response = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=b"bounded-audio",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Incomplete mobile audio body"}


@pytest.mark.anyio
async def test_mobile_streaming_limit_applies_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    class ChunkedRequest:
        async def stream(self):
            yield b"123"
            yield b"456"

    monkeypatch.setattr(endpoint, "MOBILE_AUDIO_MAX_BYTES", 5)

    with pytest.raises(HTTPException) as raised:
        await endpoint._read_audio_body(ChunkedRequest(), expected_length=None)  # type: ignore[arg-type]

    assert getattr(raised.value, "status_code", None) == 413
    assert getattr(raised.value, "detail", None) == "Mobile audio is too large"


def test_mobile_live_engine_is_server_pinned_to_elevenlabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.services import mobile_transcriptions as service

    provider = MagicMock(return_value="elevenlabs")
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(service, "resolve_runtime_transcribe_provider", provider)

    engine = service.resolve_mobile_transcription_engine()

    assert engine.tier == "pro"
    assert engine.provider == "elevenlabs"
    assert engine.model == settings.elevenlabs_transcribe_model
    provider.assert_called_once_with("elevenlabs")
