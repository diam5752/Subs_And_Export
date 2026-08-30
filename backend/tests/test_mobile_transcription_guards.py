from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
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
        content=b"validated-replay-audio",
    )

    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    probe.assert_called_once_with(b"validated-replay-audio")
    provider_gate.assert_not_called()
    credit_gate.assert_not_called()


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
