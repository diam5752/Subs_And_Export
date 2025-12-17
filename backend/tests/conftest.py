import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Mock modules that require compilation/heavy install
sys.modules["faster_whisper"] = MagicMock()
sys.modules["stable_whisper"] = MagicMock()
sys.modules["pydub"] = MagicMock()


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))

    from backend.app.api.endpoints import videos as videos_endpoints
    from backend.app.core import ratelimit
    from backend.app.services.video_processing import MediaProbe
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
