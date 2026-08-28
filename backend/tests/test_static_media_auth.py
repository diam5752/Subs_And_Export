"""Authorization regressions for locally stored private media."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend import main as backend_main
from backend.app.api.endpoints.auth import _set_media_session_cookie
from backend.app.core.database import Database
from backend.app.services.jobs import JobStore


@pytest.mark.parametrize(
    "unsafe_token",
    (
        "short",
        "a" * 42 + "=",
        "a" * 41 + "\r\n",
        "a" * 42 + ";",
    ),
)
def test_media_session_cookie_rejects_noncanonical_tokens(
    unsafe_token: str,
) -> None:
    response = Response()

    with pytest.raises(ValueError, match="Invalid media session token"):
        _set_media_session_cookie(response, unsafe_token)

    assert "set-cookie" not in response.headers


def test_media_session_cookie_accepts_generated_token_shape() -> None:
    response = Response()

    _set_media_session_cookie(response, "a" * 43)

    assert "gsubs_media_session=" + ("a" * 43) in response.headers["set-cookie"]


def _create_owned_media(
    client: TestClient,
    headers: dict[str, str],
    data_dir: Path,
    *,
    content: bytes = b"private-video",
) -> tuple[JobStore, str, Path]:
    user_response = client.get("/auth/me", headers=headers)
    assert user_response.status_code == 200
    store = JobStore(Database())
    job_id = f"private-media-{uuid.uuid4().hex}"
    store.create_job(job_id, user_response.json()["id"])
    media_path = data_dir / "artifacts" / job_id / "processed.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(content)
    return store, job_id, media_path


def _register_user(client: TestClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    email = f"static-{suffix}@example.com"
    password = "testpassword123"
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Static User"},
    )
    assert response.status_code == 200
    token_response = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    )
    assert token_response.status_code == 200
    return {"Authorization": f"Bearer {token_response.json()['access_token']}"}


def test_local_only_api_has_no_cloud_upload_routes(client: TestClient) -> None:
    # REGRESSION: production selected a retired cloud upload endpoint and made
    # every real transcription fail before the local upload could start.
    route_paths = {path for route in client.app.routes if isinstance(path := getattr(route, "path", None), str)}

    assert "/videos/gcs/upload-url" not in route_paths
    assert "/videos/gcs/process" not in route_paths
    assert client.post("/videos/gcs/upload-url").status_code == 404
    assert client.post("/videos/gcs/process").status_code == 404


def test_static_media_rejects_anonymous_requests(
    client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: local artifact URLs used to expose user media without auth.
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    client.cookies.clear()

    response = client.get("/static/artifacts/unknown-job/processed.mp4")

    assert response.status_code == 401


def test_scoped_download_grant_survives_a_browser_session_handoff(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The external browser may not have the in-app browser's session cookie."""
    from backend.app.core.config import settings

    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "download_grant_secret", SecretStr("g" * 64))
    monkeypatch.setattr(settings, "download_grant_ttl_seconds", 300)
    store, job_id, media_path = _create_owned_media(
        client,
        user_auth_headers,
        tmp_path,
        content=b"private-video-for-browser-handoff",
    )
    raw_path = f"/static/artifacts/{job_id}/{media_path.name}"

    try:
        grant_response = client.post(
            f"/videos/jobs/{job_id}/download-grant",
            headers=user_auth_headers,
            json={
                "artifact_path": raw_path,
                "filename": "Δοκιμή_subs.mp4",
            },
        )
        assert grant_response.status_code == 200
        assert grant_response.headers["cache-control"] == "private, no-store"
        grant = grant_response.json()
        assert grant["expires_in"] == 300
        assert grant["download_url"].startswith(f"{raw_path}?grant=")

        # Simulate the OS handing the URL to Safari/Chrome: no bearer and no
        # media-session cookie from the Messenger/Facebook in-app browser.
        client.cookies.clear()
        assert client.get(raw_path).status_code == 401

        download = client.get(grant["download_url"])
        assert download.status_code == 200
        assert download.content == b"private-video-for-browser-handoff"
        assert download.headers["cache-control"] == "private, no-store"
        assert download.headers["referrer-policy"] == "no-referrer"
        assert download.headers["x-robots-tag"] == "noindex, nofollow"
        assert "attachment" in download.headers["content-disposition"]
        assert "%CE%94%CE%BF%CE%BA%CE%B9%CE%BC%CE%AE_subs.mp4" in download.headers[
            "content-disposition"
        ]

        ranged = client.get(
            grant["download_url"],
            headers={"Range": "bytes=0-6"},
        )
        assert ranged.status_code == 206
        assert ranged.content == b"private"
        assert ranged.headers["accept-ranges"] == "bytes"

        grant_prefix, grant_token = grant["download_url"].split("?grant=", 1)
        encoded_payload, encoded_signature = grant_token.split(".", 1)
        tampered_signature = (
            ("a" if encoded_signature[0] != "a" else "b")
            + encoded_signature[1:]
        )
        tampered_url = (
            f"{grant_prefix}?grant={encoded_payload}.{tampered_signature}"
        )
        assert client.get(tampered_url).status_code == 401

        wrong_path_url = grant["download_url"].replace(
            media_path.name,
            "processed_1080x1920.mp4",
        )
        assert client.get(wrong_path_url).status_code == 401
    finally:
        media_path.unlink(missing_ok=True)
        media_path.parent.rmdir()
        store.delete_job(job_id)


def test_download_grant_issuance_rejects_unowned_or_noncanonical_artifacts(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.app.core.config import settings

    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "download_grant_secret", SecretStr("g" * 64))
    other_headers = _register_user(client)
    store, job_id, media_path = _create_owned_media(
        client,
        other_headers,
        tmp_path,
    )

    try:
        unowned = client.post(
            f"/videos/jobs/{job_id}/download-grant",
            headers=user_auth_headers,
            json={
                "artifact_path": f"/static/artifacts/{job_id}/{media_path.name}",
                "filename": "video.mp4",
            },
        )
        assert unowned.status_code == 404

        for invalid_path in (
            f"https://evil.example/static/artifacts/{job_id}/{media_path.name}",
            f"/static/artifacts/{job_id}/../private.mp4",
            f"/static/artifacts/{job_id}/{media_path.name}?download=true",
            f"/static/artifacts/not-{job_id}/{media_path.name}",
        ):
            response = client.post(
                f"/videos/jobs/{job_id}/download-grant",
                headers=other_headers,
                json={"artifact_path": invalid_path, "filename": "video.mp4"},
            )
            assert response.status_code == 400
    finally:
        media_path.unlink(missing_ok=True)
        media_path.parent.rmdir()
        store.delete_job(job_id)


def test_auth_me_reissues_media_cookie_for_legacy_bearer_client(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: clients logged in before the media-cookie rollout still have
    # a bearer session. Their routine profile request must restore media access.
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    token = user_auth_headers["Authorization"].removeprefix("Bearer ")
    client.cookies.clear()

    me_response = client.get("/auth/me", headers=user_auth_headers)

    assert me_response.status_code == 200
    assert client.cookies.get("gsubs_media_session") == token
    set_cookie = me_response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Path=/static" in set_cookie
    assert me_response.headers["cache-control"] == "no-store"

    store = JobStore(Database())
    job_id = f"legacy-media-{uuid.uuid4().hex}"
    store.create_job(job_id, me_response.json()["id"])
    media_path = tmp_path / "artifacts" / job_id / "processed.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"legacy-private-video")

    try:
        media_response = client.get(
            f"/static/artifacts/{job_id}/{media_path.name}",
        )
        assert media_response.status_code == 200
        assert media_response.content == b"legacy-private-video"
    finally:
        media_path.unlink(missing_ok=True)
        media_path.parent.rmdir()
        store.delete_job(job_id)


def test_cookie_scoped_logout_closes_bearerless_private_media_access(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    store, job_id, media_path = _create_owned_media(
        client,
        user_auth_headers,
        tmp_path,
    )
    media_url = f"/static/artifacts/{job_id}/{media_path.name}"

    try:
        assert client.get(media_url).status_code == 200
        assert client.post("/auth/logout").status_code == 401
        assert client.get(media_url).status_code == 200

        # REGRESSION: bearerless logout could not receive the Path=/static
        # cookie, so private media stayed accessible after apparent sign-out.
        logout = client.post(
            "/static/auth/logout",
            headers={
                "Origin": "http://testserver",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        assert logout.status_code == 200
        assert client.get(media_url).status_code == 401
    finally:
        media_path.unlink(missing_ok=True)
        media_path.parent.rmdir()
        store.delete_job(job_id)


def test_static_media_hides_another_users_job(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: knowing a job id must not reveal another account's media.
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    store, job_id, media_path = _create_owned_media(
        client,
        user_auth_headers,
        tmp_path,
    )
    other_headers = _register_user(client)

    try:
        response = client.get(
            f"/static/artifacts/{job_id}/{media_path.name}",
            headers=other_headers,
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "File not found"}
    finally:
        media_path.unlink(missing_ok=True)
        media_path.parent.rmdir()
        store.delete_job(job_id)


def test_owner_cookie_supports_range_and_safe_downloads(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: media elements need cookie auth and byte ranges, while exports
    # need an owner-only attachment response with a sanitized filename.
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    content = b"0123456789" * 200
    store, job_id, media_path = _create_owned_media(
        client,
        user_auth_headers,
        tmp_path,
        content=content,
    )
    media_url = f"/static/artifacts/{job_id}/{media_path.name}"

    try:
        range_response = client.get(
            media_url,
            headers={"Accept-Encoding": "gzip", "Range": "bytes=2-5"},
        )
        assert range_response.status_code == 206
        assert range_response.content == b"2345"
        assert range_response.headers["content-range"] == "bytes 2-5/2000"
        assert range_response.headers["cache-control"] == "private, no-store"
        assert "content-encoding" not in range_response.headers
        assert range_response.headers["content-length"] == "4"

        filename = "Ιδιωτικό βίντεο.mp4"
        download_response = client.get(
            media_url,
            headers={"Accept-Encoding": "gzip"},
            params={"download": "true", "filename": filename},
        )
        assert download_response.status_code == 200
        assert download_response.content == content
        assert "content-encoding" not in download_response.headers
        assert download_response.headers["content-length"] == str(len(content))
        assert "attachment" in download_response.headers["content-disposition"]
        assert quote(filename) in download_response.headers["content-disposition"]
    finally:
        media_path.unlink(missing_ok=True)
        media_path.parent.rmdir()
        store.delete_job(job_id)


def test_owned_job_symlink_cannot_escape_into_another_users_artifacts(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path)
    owner_store, owner_job_id, owner_media = _create_owned_media(
        client,
        user_auth_headers,
        tmp_path,
        content=b"owner",
    )
    other_headers = _register_user(client)
    other_store, other_job_id, other_media = _create_owned_media(
        client,
        other_headers,
        tmp_path,
        content=b"other-user-secret",
    )
    escape_link = owner_media.parent / "escaped.mp4"
    escape_link.symlink_to(other_media)

    try:
        response = client.get(
            f"/static/artifacts/{owner_job_id}/{escape_link.name}",
            headers=user_auth_headers,
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "File not found"}
        assert other_media.read_bytes() == b"other-user-secret"
    finally:
        escape_link.unlink(missing_ok=True)
        owner_media.unlink(missing_ok=True)
        other_media.unlink(missing_ok=True)
        owner_media.parent.rmdir()
        other_media.parent.rmdir()
        owner_store.delete_job(owner_job_id)
        other_store.delete_job(other_job_id)
