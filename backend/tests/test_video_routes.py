import base64
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.tests.process_stream import post_process_stream


@pytest.mark.parametrize(
    "authorized_credits",
    (None, True, "30", 29),
)
def test_stream_requires_a_strict_canonical_authorized_credit_tier_before_writing(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    authorized_credits: object,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    payload: dict[str, object] = {"filename": "clip.mp4"}
    if authorized_credits is not None:
        payload["authorized_credits"] = authorized_credits
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    save = MagicMock(side_effect=AssertionError("invalid authorization must precede upload writes"))
    monkeypatch.setattr(videos_module, "save_request_stream_with_limit", save)

    response = client.post(
        "/videos/process-stream",
        headers={
            **user_auth_headers,
            "Content-Type": "video/mp4",
            "X-Gsubs-Upload-Metadata": encoded,
        },
        content=b"private-video",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid upload metadata"}
    save.assert_not_called()


def test_stream_refunds_pre_body_reservation_when_authoritative_duration_exceeds_launch_cap(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module
    from backend.app.core.database import Database
    from backend.app.services.ffmpeg_utils import MediaProbe
    from backend.app.services.jobs import JobStore
    from backend.app.services.points import PointsStore

    # REGRESSION: the browser/container quote can be exactly 180.000 seconds
    # while authoritative ffprobe resolves 180.001 seconds. The launch cap must
    # fail closed and refund the already-reserved 30 credits.
    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    points_store = PointsStore(Database())
    starting_balance = points_store.get_balance(user_id)
    observed_balances: list[int] = []

    async def save_after_observing_reservation(
        _request: object,
        destination: Path,
        **_kwargs: object,
    ) -> None:
        observed_balances.append(points_store.get_balance(user_id))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"private-video")

    # The pre-body budget check uses the customer's exact 180-second quote.
    # The authoritative 180.001-second rejection happens after upload probing.
    budget_preflight = MagicMock()
    provider_dispatch = MagicMock(
        side_effect=AssertionError("duration check must precede provider dispatch"),
    )
    monkeypatch.setattr(
        videos_module,
        "probe_media",
        lambda _path: MediaProbe(duration_s=180.001, audio_codec="aac"),
    )
    monkeypatch.setattr(
        videos_module,
        "preflight_processing_provider_budget",
        budget_preflight,
    )
    monkeypatch.setattr(
        videos_module,
        "save_request_stream_with_limit",
        save_after_observing_reservation,
    )
    monkeypatch.setattr(videos_module, "run_video_processing", provider_dispatch)

    response = post_process_stream(
        client,
        funded_user_auth_headers,
        content=b"private-video",
        metadata={"authorized_credits": 30},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Video too long (max 3.0 minutes)"}
    budget_preflight.assert_called_once()
    assert observed_balances == [starting_balance - 30]
    assert points_store.get_balance(user_id) == starting_balance
    provider_dispatch.assert_not_called()
    assert JobStore(Database()).list_jobs_for_user(user_id) == []
    _data_dir, uploads_dir, artifacts_root = videos_module.data_roots()
    assert list(uploads_dir.iterdir()) == []
    assert list(artifacts_root.iterdir()) == []


def test_stream_stall_refunds_reservation_and_deletes_partial_workspace(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module
    from backend.app.core.database import Database
    from backend.app.services.jobs import JobStore
    from backend.app.services.points import PointsStore

    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    points_store = PointsStore(Database())
    starting_balance = points_store.get_balance(user_id)
    captured_path: list[Path] = []

    async def stall_after_partial_body(
        _request: object,
        destination: Path,
        *,
        expected_size: int | None,
        cleanup_on_error: bool,
    ) -> None:
        assert expected_size == len(b"private-video")
        assert cleanup_on_error is False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"partial")
        captured_path.append(destination)
        raise HTTPException(
            status_code=408,
            detail="Upload stalled before completion",
        )

    monkeypatch.setattr(
        videos_module,
        "save_request_stream_with_limit",
        stall_after_partial_body,
    )

    response = post_process_stream(
        client,
        funded_user_auth_headers,
        content=b"private-video",
        metadata={"authorized_credits": 30},
    )

    assert response.status_code == 408
    assert response.json() == {"detail": "Upload stalled before completion"}
    assert points_store.get_balance(user_id) == starting_balance
    assert JobStore(Database()).list_jobs_for_user(user_id) == []
    assert len(captured_path) == 1
    assert not captured_path[0].exists()
    _data_dir, uploads_dir, artifacts_root = videos_module.data_roots()
    assert list(uploads_dir.iterdir()) == []
    assert list(artifacts_root.iterdir()) == []


def test_stream_rejects_nan_probe_with_full_cleanup_and_refund(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module
    from backend.app.core.database import Database
    from backend.app.core.workspace_ownership import get_workspace_owner
    from backend.app.services.ffmpeg_utils import MediaProbe
    from backend.app.services.jobs import JobStore
    from backend.app.services.points import PointsStore

    # REGRESSION: NaN compares false to both <= 0 and > max. It previously
    # escaped duration validation, then raised during pricing without removing
    # the private upload or its ownership marker.
    fixed_uuid = uuid.UUID("22222222-2222-4222-8222-222222222222")
    uuid_namespace = MagicMock()
    uuid_namespace.uuid4.return_value = fixed_uuid
    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    points_store = PointsStore(Database())
    starting_balance = points_store.get_balance(user_id)
    budget_preflight = MagicMock()
    provider_dispatch = MagicMock(
        side_effect=AssertionError("invalid duration must precede provider dispatch"),
    )
    journal = MagicMock()
    monkeypatch.setattr(
        videos_module,
        "probe_media",
        lambda _path: MediaProbe(duration_s=float("nan"), audio_codec="aac"),
    )
    monkeypatch.setattr(videos_module, "uuid", uuid_namespace)
    monkeypatch.setattr(
        videos_module,
        "preflight_processing_provider_budget",
        budget_preflight,
    )
    monkeypatch.setattr(videos_module, "run_video_processing", provider_dispatch)
    monkeypatch.setattr(videos_module, "configured_erasure_journal", lambda: journal)

    response = post_process_stream(
        client,
        funded_user_auth_headers,
        content=b"private-video",
        metadata={"authorized_credits": 30},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Could not determine video duration"}
    budget_preflight.assert_called_once()
    assert points_store.get_balance(user_id) == starting_balance
    provider_dispatch.assert_not_called()
    journal.append.assert_called_once_with(
        kind="job",
        user_id=user_id,
        job_ids=[str(fixed_uuid)],
    )
    uuid_namespace.uuid4.assert_called_once_with()
    data_dir, uploads_dir, artifacts_root = videos_module.data_roots()
    job_id = str(fixed_uuid)
    assert JobStore(Database()).list_jobs_for_user(user_id) == []
    assert list(uploads_dir.iterdir()) == []
    assert list(artifacts_root.iterdir()) == []
    assert get_workspace_owner(data_dir=data_dir, job_id=job_id) is None


def test_stream_upload_writes_the_browser_body_directly_once(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    captured: dict[str, object] = {}

    def capture_processing(_job_id, input_path, *_args, **_kwargs) -> None:
        captured["path"] = input_path
        captured["content"] = input_path.read_bytes()

    monkeypatch.setattr(videos_module, "run_video_processing", capture_processing)
    raw_video = b"direct-stream-video"

    response = post_process_stream(
        client,
        funded_user_auth_headers,
        filename="κινητό.mp4",
        content=raw_video,
        metadata={
            "transcribe_tier": "standard",
            "transcribe_provider": "mock",
        },
    )

    # REGRESSION: multipart parsing first spooled the complete request and then
    # copied it again. The optimized route streams the raw browser body into
    # the canonical upload path consumed by processing.
    assert response.status_code == 200
    assert captured["content"] == raw_video
    assert str(captured["path"]).endswith("_input.mp4")


def test_stream_upload_rejects_invalid_metadata_before_writing(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/videos/process-stream",
        headers={
            **user_auth_headers,
            "Content-Type": "video/mp4",
            "X-Gsubs-Upload-Metadata": "not-base64",
        },
        content=b"video",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"


def test_stream_upload_cors_preflight_allows_metadata_header(client: TestClient) -> None:
    response = client.options(
        "/videos/process-stream",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": ("authorization,content-type,x-gsubs-upload-metadata"),
        },
    )

    assert response.status_code == 200
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-gsubs-upload-metadata" in allowed_headers


def test_legacy_multipart_upload_route_is_absent(client: TestClient) -> None:
    # REGRESSION: UploadFile parsing spooled multipart bodies before bearer
    # authentication and before the backend's byte limit could run.
    route_paths = {path for route in client.app.routes if isinstance(path := getattr(route, "path", None), str)}

    assert "/videos/process" not in route_paths
    response = client.post(
        "/videos/process",
        files={"file": ("legacy.mp4", b"legacy", "video/mp4")},
    )
    assert response.status_code == 404


def test_legacy_manual_admin_routes_are_absent(client: TestClient) -> None:
    # REGRESSION: retention and usage reporting run through the controlled
    # scheduler/CLI paths, not public HTTP routes guarded by an email allowlist.
    route_paths = {path for route in client.app.routes if isinstance(path := getattr(route, "path", None), str)}

    assert "/videos/jobs/cleanup" not in route_paths
    assert "/videos/admin/usage/summary" not in route_paths
    assert client.post("/videos/jobs/cleanup").status_code in {404, 405}
    assert client.get("/videos/admin/usage/summary").status_code == 404


def test_stream_upload_authenticates_before_consuming_body(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    save_called = False

    async def capture_save(*_args, **_kwargs) -> int:
        nonlocal save_called
        save_called = True
        return 0

    monkeypatch.setattr(videos_module, "save_request_stream_with_limit", capture_save)
    response = post_process_stream(client, {}, content=b"unauthenticated-private-video")

    assert response.status_code == 401
    assert save_called is False


def test_stream_upload_rejects_oversized_content_length(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    monkeypatch.setattr(videos_module, "MAX_UPLOAD_BYTES", 1024)
    response = post_process_stream(
        client,
        user_auth_headers,
        content=b"data",
        extra_headers={"content-length": "1025"},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_stream_upload_rejects_malformed_content_length(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = post_process_stream(
        client,
        user_auth_headers,
        content=b"data",
        extra_headers={"content-length": "not-a-number"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Content-Length header"


def test_stream_upload_rejects_before_writing_when_storage_reserve_is_low(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    def reject_storage(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=507, detail="Storage is temporarily busy")

    monkeypatch.setattr(videos_module, "require_storage_capacity", reject_storage)

    response = post_process_stream(client, user_auth_headers, content=b"data")

    # REGRESSION: a low-disk server previously accepted the upload and failed
    # only after it had started consuming storage and user time.
    assert response.status_code == 507
    assert response.json()["detail"] == "Storage is temporarily busy"
