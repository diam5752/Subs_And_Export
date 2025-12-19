import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Set trusted hosts BEFORE any app import
os.environ.setdefault("GSP_TRUSTED_HOSTS", "localhost,testserver")
os.environ.setdefault("APP_ENV", "dev")

# Mock modules that require compilation/heavy install
sys.modules["faster_whisper"] = MagicMock()
sys.modules["stable_whisper"] = MagicMock()
sys.modules["pydub"] = MagicMock()


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("GSP_TRUSTED_HOSTS", "*")  # Allow test client requests

    from backend.app.api.endpoints import videos as videos_endpoints
    from backend.app.core import ratelimit
    from backend.app.services.ffmpeg_utils import MediaProbe
    from backend.main import app

    ratelimit.limiter_login.reset()
    ratelimit.limiter_register.reset()
    ratelimit.limiter_processing.reset()
    ratelimit.limiter_content.reset()

    monkeypatch.setattr(
        videos_endpoints,
        "probe_media",
        lambda _path: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_auth_headers(client: TestClient) -> dict[str, str]:
    password = "testpassword123"
    email = "test@example.com"

    client.post("/auth/register", json={"email": email, "password": password, "name": "Test User"})
    token = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def prevent_paid_api_calls(monkeypatch):
    """
    Prevent tests from making expensive API calls.
    1. Remove API keys from environment.
    2. Mock secrets loading to prevent leaking keys from secrets.toml.
    3. Patch internal resolvers to always return None.
    """
    # 1. Strip Env Vars
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    # 2. Block secrets.toml access
    # We patch toml.load to return empty dict wherever it might be used for secrets.
    # Currently subtitles.py is the main consumer.
    try:
        monkeypatch.setattr("backend.app.services.subtitles.toml.load", lambda x: {})
    except (ImportError, AttributeError):
        pass

    # 3. Patch specific key resolvers in known modules
    # These override the logic to ALWAYS return None unless set by test env var (which we deleted)
    try:
        monkeypatch.setattr("backend.app.services.subtitles._resolve_openai_api_key", lambda *args: None)
        monkeypatch.setattr("backend.app.services.subtitles._resolve_groq_api_key", lambda *args: None)
    except (ImportError, AttributeError):
        pass
        
    try:
        monkeypatch.setattr("backend.app.services.transcription.openai_cloud._resolve_openai_api_key", lambda *args: None)
        monkeypatch.setattr("backend.app.services.transcription.groq_cloud._resolve_groq_api_key", lambda *args: None)
    except (ImportError, AttributeError):
        pass
