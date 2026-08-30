from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.services.ffmpeg_utils import MediaProbe
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore


def _headers(auth: dict[str, str], *, key: str = "mobile-request-0001") -> dict[str, str]:
    return {
        **auth,
        "Content-Type": "audio/mp4",
        "Idempotency-Key": key,
        "X-Gsubs-Authorized-Credits": "30",
    }


def _user_id(client: TestClient, headers: dict[str, str]) -> str:
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    return str(response.json()["id"])


def test_mobile_transcription_keeps_video_and_audio_out_of_server_storage(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    monkeypatch.setattr(settings, "mock_external_services", True)
    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )
    user_id = _user_id(client, funded_user_auth_headers)
    points = PointsStore(Database())
    starting_balance = points.get_balance(user_id)

    first = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers),
        content=b"bounded-aac-audio",
    )
    replay = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers),
        content=b"bounded-aac-audio",
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert first.headers["cache-control"] == "private, no-store"
    payload = first.json()
    assert payload["credits_charged"] == 30
    assert payload["video_uploaded"] is False
    assert payload["server_media_retained"] is False
    assert payload["cues"]
    assert points.get_balance(user_id) == starting_balance - 30
    jobs = JobStore(Database()).list_jobs_for_user(user_id)
    assert len(jobs) == 1
    assert jobs[0].status == "completed"
    assert "cues" not in (jobs[0].result_data or {})
    uploads = settings.data_dir / "uploads"
    artifacts = settings.data_dir / "artifacts"
    assert not uploads.exists() or list(uploads.iterdir()) == []
    assert not artifacts.exists() or list(artifacts.iterdir()) == []


def test_mobile_transcription_uses_authoritative_audio_duration_before_charging(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=181.0, audio_codec="aac"),
    )
    user_id = _user_id(client, funded_user_auth_headers)
    points = PointsStore(Database())
    starting_balance = points.get_balance(user_id)

    response = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers),
        content=b"bounded-aac-audio",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Audio too long (max 3.0 minutes)"}
    assert points.get_balance(user_id) == starting_balance
    assert JobStore(Database()).list_jobs_for_user(user_id) == []


def test_mobile_transcription_rejects_video_stream_before_charge_or_dispatch(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(
            duration_s=10.0,
            audio_codec="aac",
            has_video=True,
        ),
    )
    dispatch = MagicMock(side_effect=AssertionError("video must be rejected before dispatch"))
    monkeypatch.setattr(endpoint, "process_mobile_transcription", dispatch)
    user_id = _user_id(client, funded_user_auth_headers)
    points = PointsStore(Database())
    starting_balance = points.get_balance(user_id)

    response = client.post(
        "/videos/mobile-transcriptions",
        headers=_headers(funded_user_auth_headers, key="mobile-request-with-video"),
        content=b"mp4-with-video-and-aac",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Mobile audio must not contain video"}
    dispatch.assert_not_called()
    assert points.get_balance(user_id) == starting_balance
    assert JobStore(Database()).list_jobs_for_user(user_id) == []


def test_mobile_transcription_replay_rejects_a_video_body_before_returning_result(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    monkeypatch.setattr(settings, "mock_external_services", True)
    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )
    headers = _headers(funded_user_auth_headers, key="mobile-video-replay")
    first = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=b"bounded-aac-audio",
    )
    assert first.status_code == 200, first.text
    user_id = _user_id(client, funded_user_auth_headers)
    points = PointsStore(Database())
    balance_after_first = points.get_balance(user_id)

    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(
            duration_s=10.0,
            audio_codec="aac",
            has_video=True,
        ),
    )
    dispatch = MagicMock(side_effect=AssertionError("video replay must not dispatch"))
    monkeypatch.setattr(endpoint, "process_mobile_transcription", dispatch)
    replay = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=b"mp4-with-video-and-aac",
    )

    assert replay.status_code == 400
    assert replay.json() == {"detail": "Mobile audio must not contain video"}
    dispatch.assert_not_called()
    assert points.get_balance(user_id) == balance_after_first
    assert len(JobStore(Database()).list_jobs_for_user(user_id)) == 1


def test_mobile_transcription_rejects_non_audio_before_probe(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint

    probe = MagicMock(side_effect=AssertionError("invalid MIME must precede probing"))
    monkeypatch.setattr(endpoint, "probe_media_bytes", probe)
    headers = _headers(funded_user_auth_headers)
    headers["Content-Type"] = "video/mp4"

    response = client.post(
        "/videos/mobile-transcriptions",
        headers=headers,
        content=b"private-video",
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported mobile audio type"}
    probe.assert_not_called()


def test_mobile_transcription_refunds_when_transcription_fails(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import mobile_transcriptions as endpoint
    from backend.app.services import mobile_transcriptions as service

    monkeypatch.setattr(settings, "mock_external_services", True)
    monkeypatch.setattr(
        endpoint,
        "probe_media_bytes",
        lambda _body: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )
    monkeypatch.setattr(
        service,
        "_dispatch_audio",
        MagicMock(side_effect=RuntimeError("provider failed")),
    )
    user_id = _user_id(client, funded_user_auth_headers)
    points = PointsStore(Database())
    starting_balance = points.get_balance(user_id)

    with pytest.raises(RuntimeError, match="provider failed"):
        client.post(
            "/videos/mobile-transcriptions",
            headers=_headers(funded_user_auth_headers, key="mobile-request-failure"),
            content=b"bounded-aac-audio",
        )

    assert points.get_balance(user_id) == starting_balance
    jobs = JobStore(Database()).list_jobs_for_user(user_id)
    assert len(jobs) == 1
    assert jobs[0].status == "failed"


def test_mobile_transcription_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/videos/mobile-transcriptions",
        headers={
            "Content-Type": "audio/mp4",
            "Idempotency-Key": "mobile-request-unauthenticated",
            "X-Gsubs-Authorized-Credits": "30",
        },
        content=b"bounded-aac-audio",
    )

    assert response.status_code == 401
