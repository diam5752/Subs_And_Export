import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api.endpoints import export_routes, videos
from backend.app.core import auth as backend_auth
from backend.app.core.database import Database
from backend.app.services import jobs


def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    try:
        client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "Test"})
    except:
        pass
    token = client.post("/auth/token", data={"username": email, "password": "testpassword123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _parse_srt_file(path: Path) -> list[tuple[float, float, str]]:
    def parse_timestamp(value: str) -> float:
        hours, minutes, seconds = value.replace(",", ".").split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    entries: list[tuple[float, float, str]] = []
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    for block in content.split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        timing_index = 0 if "-->" in lines[0] else 1
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            continue

        start_raw, end_raw = [part.strip() for part in lines[timing_index].split("-->", maxsplit=1)]
        text = "\n".join(lines[timing_index + 1:])
        entries.append((parse_timestamp(start_raw), parse_timestamp(end_raw), text))
    return entries


@pytest.mark.parametrize(
    ("resolution", "expected_name", "expected_snippet"),
    [
        ("srt", "processed.srt", "00:00:00,500 --> 00:00:01,500"),
        ("vtt", "processed.vtt", "00:00:00.500 --> 00:00:01.500"),
        ("txt", "processed.txt", "Hello world"),
    ],
)
def test_subtitle_file_export_success(
    client: TestClient,
    monkeypatch,
    tmp_path: Path,
    resolution: str,
    expected_name: str,
    expected_snippet: str,
):
    # Setup environment - patch the settings object project_root attribute
    from backend.app.core.config import settings
    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(videos, "_data_roots", lambda: (tmp_path, tmp_path / "uploads", tmp_path / "artifacts"))
    monkeypatch.setattr(export_routes, "data_roots", lambda: (tmp_path, tmp_path / "uploads", tmp_path / "artifacts"))

    # Setup DB
    db = Database()
    store = jobs.JobStore(db)
    email = f"srt_{uuid.uuid4().hex}@example.com"
    user_id = backend_auth.UserStore(db=db).register_local_user(email, "testpassword123", "User").id

    # Create Job
    job = store.create_job(f"srt-job-{uuid.uuid4().hex}", user_id)
    artifact_dir = tmp_path / "artifacts" / job.id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Add dummy transcription
    cues = [
        {"start": 0.5, "end": 1.5, "text": "Hello world"},
        {"start": 2.0, "end": 3.0, "text": "Testing SRT"}
    ]
    (artifact_dir / "transcription.json").write_text(json.dumps(cues))
    job.status = "completed" # Must be completed
    store.update_job(job.id, status="completed", result_data={}) # Ensure result_data dict exists

    # Override get_job_store dep
    from backend.app.api.deps import get_db, get_job_store
    from backend.main import app
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        headers = _auth_header(client, email)

        # Trigger export
        resp = client.post(
            f"/videos/jobs/{job.id}/export",
            headers=headers,
            json={"resolution": resolution}
        )

        assert resp.status_code == 200, f"Status: {resp.status_code}, Body: {resp.text}"

        # Verify file creation
        export_path = artifact_dir / expected_name
        assert export_path.exists()
        content = export_path.read_text()
        assert "Hello world" in content
        assert expected_snippet in content

        # Verify job update
        updated_job = store.get_job(job.id)
        assert updated_job.result_data["variants"][resolution].endswith(f"/{expected_name}")

    finally:
        app.dependency_overrides = {}


def test_subtitle_file_export_resegments_long_word_timed_cues(
    client: TestClient,
    monkeypatch,
    tmp_path: Path,
):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(videos, "_data_roots", lambda: (tmp_path, tmp_path / "uploads", tmp_path / "artifacts"))
    monkeypatch.setattr(export_routes, "data_roots", lambda: (tmp_path, tmp_path / "uploads", tmp_path / "artifacts"))

    db = Database()
    store = jobs.JobStore(db)
    email = f"resegment_{uuid.uuid4().hex}@example.com"
    user_id = backend_auth.UserStore(db=db).register_local_user(email, "testpassword123", "User").id

    job = store.create_job(f"resegment-job-{uuid.uuid4().hex}", user_id)
    artifact_dir = tmp_path / "artifacts" / job.id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    words = [
        "ΓΕΙΑ", "ΣΑΣ,", "ΜΕ", "ΛΕΝΕ", "ΙΑΝΝΗ.", "ΕΙΜΑΙ", "ΑΠΟ", "ΤΗΝ", "ΑΜΕΡΙΚΗ.",
        "Ο", "ΠΑΤΕΡΑΣ", "ΜΟΥ", "ΕΙΝΑΙ", "ΑΠΟ", "ΤΗΝ", "ΜΑΚΕΔΟΝΙΑ,", "ΣΕΡΡΕΣ,",
        "ΑΛΛΑ", "Ο", "ΠΑΠΠΟΥΣ", "ΜΟΥ", "ΚΑΙ", "Η", "ΓΙΑΓΙΑ", "ΜΟΥ", "ΗΤΑΝ",
        "ΠΡΟΣΦΥΓΕΣ", "ΑΠΟ", "ΤΗΝ", "ΘΡΑΚΗ.",
    ]
    word_timings = []
    cursor = 0.0
    for word in words:
        next_cursor = cursor + 0.5
        word_timings.append({"start": cursor, "end": next_cursor, "text": word})
        cursor = next_cursor

    cues = [{
        "start": 0.0,
        "end": cursor,
        "text": " ".join(words),
        "words": word_timings,
    }]
    (artifact_dir / "transcription.json").write_text(json.dumps(cues), encoding="utf-8")
    store.update_job(
        job.id,
        status="completed",
        result_data={"max_subtitle_lines": 2, "subtitle_size": 85},
    )

    from backend.app.api.deps import get_db, get_job_store
    from backend.main import app
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        headers = _auth_header(client, email)
        resp = client.post(
            f"/videos/jobs/{job.id}/export",
            headers=headers,
            json={"resolution": "srt"},
        )

        assert resp.status_code == 200, resp.text

        export_path = artifact_dir / "processed.srt"
        exported = _parse_srt_file(export_path)
        assert len(exported) >= 2
        assert exported[0][1] < cursor
        assert "ΓΕΙΑ ΣΑΣ" in exported[0][2]
        assert any("ΘΡΑΚΗ" in text for _, _, text in exported)
    finally:
        app.dependency_overrides = {}
