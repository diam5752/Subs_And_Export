
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from backend.app.services import tiktok

class TestTikTokEndpoints:
    def test_get_url_no_config(self, client):
        """Test URL generation fails gracefully without config."""
        # Need to login first
        client.post("/auth/register", json={"email": "nocfg@e.com", "password": "testpassword123", "name": "NC"})
        token = client.post("/auth/token", data={"username": "nocfg@e.com", "password": "testpassword123"}).json()["access_token"]
        
        response = client.get("/tiktok/url", headers={"Authorization": f"Bearer {token}"})
        # In test env we might not have secrets, should be 503
        assert response.status_code == 503

    def test_get_url_with_config(self, client, monkeypatch):
        """Test URL generation with config."""
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "key")
        monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "secret")
        monkeypatch.setenv("TIKTOK_REDIRECT_URI", "uri")
        
        # Must be logged in
        client.post("/auth/register", json={"email": "tt@e.com", "password": "testpassword123", "name": "TT"})
        token = client.post("/auth/token", data={"username": "tt@e.com", "password": "testpassword123"}).json()["access_token"]
        
        response = client.get("/tiktok/url", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "state" in data

    def test_callback_flow(self, client, monkeypatch):
        """Test callback and history recording."""
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "key")
        monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "secret")
        monkeypatch.setenv("TIKTOK_REDIRECT_URI", "uri")
        
        # Mock exchange
        mock_tokens = tiktok.TikTokTokens("acc", "ref", 3600, 1000)
        monkeypatch.setattr(tiktok, "exchange_code_for_token", lambda c, code: mock_tokens)
        
        # Login
        client.post("/auth/register", json={"email": "c@e.com", "password": "testpassword123", "name": "C"})
        token = client.post("/auth/token", data={"username": "c@e.com", "password": "testpassword123"}).json()["access_token"]
        
        response = client.post(
            "/tiktok/callback",
            json={"code": "123", "state": "s"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["access_token"] == "acc"
        
        # Verify history
        h_res = client.get("/history/", headers={"Authorization": f"Bearer {token}"})
        assert h_res.status_code == 200
        events = h_res.json()
        assert len(events) > 0
        assert events[0]["kind"] == "tiktok_auth"

    def test_upload_flow(self, client, monkeypatch, tmp_path):
        """Test upload flow."""
        # Setup Env
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "key")
        monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "secret")
        monkeypatch.setenv("TIKTOK_REDIRECT_URI", "uri")
        
        # Patch PROJECT_ROOT to verify path security logic works with tmp paths
        from backend.app.core import config
        # The endpoint now uses config.PROJECT_ROOT / "data" instead of config.PROJECT_ROOT.parent / "data"
        fake_project_root = tmp_path / "project"
        fake_project_root.mkdir(parents=True)
        monkeypatch.setattr(config, "PROJECT_ROOT", fake_project_root)
        
        # Mock Upload
        monkeypatch.setattr(tiktok, "upload_video", lambda t, p, title, desc: {"id": "vid1"})
        
        # Login
        client.post("/auth/register", json={"email": "u@e.com", "password": "testpassword123", "name": "U"})
        token = client.post("/auth/token", data={"username": "u@e.com", "password": "testpassword123"}).json()["access_token"]
        
        # Create fake video in data dir
        # endpoint looks at: config.PROJECT_ROOT / "data"
        data_dir = fake_project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        vid_path = data_dir / "test_vid.mp4"
        vid_path.write_bytes(b"video data")
        
        # The endpoint validates `str(full_path).startswith(str(data_dir.resolve()))`
        # We send `video_path="data/test_vid.mp4"`
        # If config.PROJECT_ROOT is /tmp/.../project
        # data_dir is /tmp/.../project/data
        # 
        # The endpoint constructs: (config.PROJECT_ROOT / req.video_path).resolve()
        # If req.video_path is "data/test_vid.mp4", it becomes /tmp/.../project/data/test_vid.mp4
        # This matches data_dir/test_vid.mp4
        # So it should pass.
        
        response = client.post(
            "/tiktok/upload",
            json={
                "access_token": "acc", 
                "video_path": "data/test_vid.mp4",
                "title": "T",
                "description": "D"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["id"] == "vid1"
        
        # Verify history
        h_res = client.get("/history/", headers={"Authorization": f"Bearer {token}"})
        events = h_res.json()
        assert events[0]["kind"] == "tiktok_upload"
