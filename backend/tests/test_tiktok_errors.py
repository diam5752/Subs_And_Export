from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.endpoints import tiktok as tiktok_ep
from backend.app.core import config as backend_config
from backend.app.services import tiktok


def _auth_header(client: TestClient, email: str = "tt-errors@example.com") -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "TikTok"})
    token = client.post("/auth/token", data={"username": email, "password": "testpassword123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_tiktok_callback_requires_config(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="missingcfg@example.com")
    monkeypatch.setattr(tiktok_ep, "tiktok", tiktok_ep.tiktok)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "")
    resp = client.post("/tiktok/callback", json={"code": "abc", "state": "s"}, headers=headers)
    assert resp.status_code == 503


def test_tiktok_callback_handles_errors(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="err@example.com")
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "u")

    class Boom(tiktok.TikTokError):
        pass

    monkeypatch.setattr(tiktok_ep.tiktok, "exchange_code_for_token", lambda cfg, code: (_ for _ in ()).throw(Boom("bad")) )
    resp = client.post("/tiktok/callback", json={"code": "abc", "state": "s"}, headers=headers)
    assert resp.status_code == 400


def test_tiktok_callback_handles_generic_error(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="generic@example.com")
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "u")

    monkeypatch.setattr(tiktok_ep.tiktok, "exchange_code_for_token", lambda cfg, code: (_ for _ in ()).throw(RuntimeError("oops")))
    resp = client.post("/tiktok/callback", json={"code": "abc", "state": "s"}, headers=headers)
    assert resp.status_code == 400


def test_tiktok_upload_path_validation(client: TestClient, monkeypatch, tmp_path: Path):
    headers = _auth_header(client, email="path@example.com")
    monkeypatch.setattr(backend_config, "PROJECT_ROOT", tmp_path)

    # Path outside data dir triggers 403
    resp = client.post(
        "/tiktok/upload",
        json={"access_token": "tok", "video_path": "../secret.mp4", "title": "t", "description": "d"},
        headers=headers,
    )
    assert resp.status_code == 403

    # Missing file inside data dir triggers 404
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    resp2 = client.post(
        "/tiktok/upload",
        json={"access_token": "tok", "video_path": "data/missing.mp4", "title": "t", "description": "d"},
        headers=headers,
    )
    assert resp2.status_code == 404


def test_tiktok_upload_handles_errors(client: TestClient, monkeypatch, tmp_path: Path):
    headers = _auth_header(client, email="uploaderr@example.com")
    monkeypatch.setattr(backend_config, "PROJECT_ROOT", tmp_path)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "clip.mp4"
    file_path.write_bytes(b"video")

    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "u")

    def boom(tokens, path, title, desc):
        raise tiktok.TikTokError("upload failed")

    monkeypatch.setattr(tiktok_ep.tiktok, "upload_video", boom)

    resp = client.post(
        "/tiktok/upload",
        json={"access_token": "tok", "video_path": "data/clip.mp4", "title": "t", "description": "d"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_tiktok_upload_generic_failure(client: TestClient, monkeypatch, tmp_path: Path):
    headers = _auth_header(client, email="uploadgeneric@example.com")
    monkeypatch.setattr(backend_config, "PROJECT_ROOT", tmp_path)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "clip2.mp4").write_bytes(b"video")

    def boom(tokens, path, title, desc):
        raise RuntimeError("crash")

    monkeypatch.setattr(tiktok_ep.tiktok, "upload_video", boom)

    resp = client.post(
        "/tiktok/upload",
        json={"access_token": "tok", "video_path": "data/clip2.mp4", "title": "t", "description": "d"},
        headers=headers,
    )
    assert resp.status_code == 500
