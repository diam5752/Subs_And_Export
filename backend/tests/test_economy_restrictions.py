from unittest.mock import MagicMock

from backend.app.core import config
from backend.app.services.jobs import JobStore
from backend.app.services.ffmpeg_utils import MediaProbe


def test_concurrent_jobs_limit_process(client, user_auth_headers, monkeypatch):
    # Mock count_active_jobs_for_user to return limit + 1
    monkeypatch.setattr(JobStore, "count_active_jobs_for_user", lambda self, uid: config.settings.max_concurrent_jobs + 1)

    # Mock probe_media to avoid actual file processing (though it happens after check)
    monkeypatch.setattr("backend.app.api.endpoints.videos.probe_media", lambda p: MediaProbe(duration_s=10.0, audio_codec="aac"))

    files = {"file": ("video.mp4", b"fake content", "video/mp4")}

    response = client.post(
        "/videos/process",
        files=files,
        headers=user_auth_headers,
        data={"transcribe_model": "standard"}
    )

    assert response.status_code == 429, f"Expected 429, got {response.status_code}: {response.text}"
    assert "Too many active jobs" in response.json()["detail"]

def test_video_duration_limit(client, user_auth_headers, monkeypatch):
    # Mock count to return 0
    monkeypatch.setattr(JobStore, "count_active_jobs_for_user", lambda self, uid: 0)

    # Mock probe_media to return duration > MAX
    def mock_probe(path):
        return MediaProbe(duration_s=config.settings.max_video_duration_seconds + 10, audio_codec="aac")

    monkeypatch.setattr("backend.app.api.endpoints.videos.probe_media", mock_probe)

    files = {"file": ("video.mp4", b"fake content", "video/mp4")}

    response = client.post(
        "/videos/process",
        files=files,
        headers=user_auth_headers,
        data={"transcribe_model": "standard"}
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    assert "Video too long" in response.json()["detail"]

def test_allowed_video(client, user_auth_headers, monkeypatch):
    # Mock count to return 0
    monkeypatch.setattr(JobStore, "count_active_jobs_for_user", lambda self, uid: 0)

    # Mock probe_media to return duration OK
    def mock_probe(path):
        return MediaProbe(duration_s=100.0, audio_codec="aac")

    monkeypatch.setattr("backend.app.api.endpoints.videos.probe_media", mock_probe)

    # Mock background tasks so we don't actually run processing
    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", MagicMock())

    files = {"file": ("video.mp4", b"fake content", "video/mp4")}

    response = client.post(
        "/videos/process",
        files=files,
        headers=user_auth_headers,
        data={"transcribe_model": "standard"}
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
