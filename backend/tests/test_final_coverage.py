
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.common import cleanup
from backend.app.core import auth
from backend.app.services import subtitles

# ==========================================
# Videos Endpoint Coverage (app/api/endpoints/videos.py)
# ==========================================

def test_parse_resolution_error():
    """Cover exception path in _parse_resolution (lines 106-107)."""
    assert videos._parse_resolution("100xInvalid") == (None, None)

def test_ensure_job_size_exception():
    """Cover exception path in _ensure_job_size (lines 328-329)."""
    # Create a job with a path that exists but stat() fails
    mock_job = MagicMock()
    mock_job.status = "completed"
    mock_job.result_data = {"video_path": "foo.mp4"}

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.stat", side_effect=Exception("Stat failed")):
             # Should safe catch
             videos._ensure_job_size(mock_job)

def test_create_viral_metadata_generic_exception(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Cover generic exception in create_viral_metadata - SKIPPED: viral_metadata feature removed."""
    import pytest
    pytest.skip("viral_metadata feature removed")
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(id="u1", email="e@e.com", name="u", provider="local")
    app_overrides = {deps.get_current_user: mock_get_current_user}

    class MockJobStore:
        def get_job(self, jid):
            return Job(id=jid, user_id="u1", status="completed", progress=100,
                       message="d", created_at=0, updated_at=0, result_data={})

    app_overrides[deps.get_job_store] = lambda: MockJobStore()

    # Stub file existence
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        art_root = tpath / "artifacts"
        job_dir = art_root / "j1"
        job_dir.mkdir(parents=True)
        (job_dir / "transcript.txt").write_text("content")

        monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (tpath, tpath, art_root))

        # Force exception in generate_viral_metadata
        def mock_gen(*args):
            raise ValueError("Boom")
        monkeypatch.setattr("backend.app.api.endpoints.videos.generate_viral_metadata", mock_gen)

        from backend.main import app
        app.dependency_overrides = app_overrides
        try:
            resp = client.post("/videos/jobs/j1/viral-metadata", headers=user_auth_headers)
            assert resp.status_code == 500
            assert "Boom" in resp.json()["detail"]
        finally:
            app.dependency_overrides = {}


# ==========================================
# Cleanup Coverage (app/common/cleanup.py)
# ==========================================

def test_cleanup_check_and_delete_not_exists():
    """Cover early return in check_and_delete (line 28)."""
    # This is an inner function, so we must call cleanup_old_jobs in a way that triggers it.
    # Actually it iterates iterdir(). If we mock iterdir to return a path that then doesn't exist?
    # Race condition simulation.

    mock_path = MagicMock(spec=Path)
    mock_path.name = "foo"
    # First call exists() is for the dir loop? No, it calls check_and_delete(item).
    # inside check_and_delete: if not path.exists(): return
    # So we need mock_path.exists() to return False.
    mock_path.exists.return_value = False

    with patch("backend.app.common.cleanup.Path.iterdir", return_value=[mock_path]):
         # We need to pass valid Path objects to the function, but we mocked iterdir on them?
         # Easier: Pass a real dir that has a file, but mock the inner check?
         # Or just unit test the inner function logic if we could import it? No it's local.
         # We can simulate race condition: iterdir returns an item, but then check_and_delete logic calls exists() which returns False.

         # The function takes uploads_dir.
         mock_dir = MagicMock()
         mock_dir.exists.return_value = True
         mock_dir.iterdir.return_value = [mock_path]

         # unexpected bool was caused by passing False. Use a Mock for the other arg too.
         mock_artifacts = MagicMock()
         mock_artifacts.exists.return_value = False

         cleanup.cleanup_old_jobs(mock_dir, mock_artifacts)

def test_cleanup_skip_gitkeep_explicit():
    """Cover .gitkeep skip (line 53)."""
    # We covered line 46 in uploads, now line 53 in artifacts
    mock_uploads = MagicMock()
    mock_uploads.exists.return_value = False

    mock_dir = MagicMock()
    mock_dir.exists.return_value = True
    mock_gitkeep = MagicMock()
    mock_gitkeep.name = ".gitkeep"
    mock_dir.iterdir.return_value = [mock_gitkeep]

    cleanup.cleanup_old_jobs(mock_uploads, mock_dir)
    # properly skipped if no error/delete call on it
    mock_gitkeep.unlink.assert_not_called()

def test_process_video_content_length_invalid(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Cover invalid content-length header (line 253)."""
    # If content-length is not an int, it passes (ValueError caught)
    headers = user_auth_headers.copy()
    headers["content-length"] = "invalid"

    files = {"file": ("test.mp4", b"data", "video/mp4")}

    # Needs to pass deps
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_user():
        return User(id="u1", email="e", name="n", provider="local")

    class MockStore:
        def create_job(self, *args, **_kwargs):
            return Job(
                id="j1", user_id="u1", status="queued", progress=0,
                message="queued", created_at=0, updated_at=0, result_data={}
            )

        def count_active_jobs_for_user(self, user_id):
            return 0

    class MockPointsStore:
        def spend(self, *_args, **_kwargs):
            return 999

    class MockLedgerStore:
        pass

    app_overrides = {
        deps.get_current_user: mock_user,
        deps.get_job_store: lambda: MockStore(),
        deps.get_points_store: lambda: MockPointsStore(),
        deps.get_usage_ledger_store: lambda: MockLedgerStore(),
    }

    # Mock save to avoid disk I/O
    monkeypatch.setattr("backend.app.api.endpoints.videos._save_upload_with_limit", lambda *args: None)
    monkeypatch.setattr("backend.app.api.endpoints.videos.reserve_processing_charges", lambda *args, **kwargs: (None, 999))
    # Mock background task add to avoid running processing
    monkeypatch.setattr("starlette.background.BackgroundTasks.add_task", lambda *args, **kwargs: None)

    # Mock dirs
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (tpath, tpath, tpath))

        from backend.main import app
        app.dependency_overrides = app_overrides
        try:
            resp = client.post("/videos/process", headers=headers, files=files)
            assert resp.status_code == 200
        finally:
            app.dependency_overrides = {}

def test_create_viral_metadata_job_not_found(client: TestClient, user_auth_headers: dict):
    """Cover Job not found - SKIPPED: viral_metadata feature removed."""
    import pytest
    pytest.skip("viral_metadata feature removed")
    from backend.app.api import deps
    from backend.app.core.auth import User

    async def mock_user():
        return User(id="u1", email="e", name="n", provider="local")

    class MockStore:
        def get_job(self, jid):
            return None # Job not found

    app_overrides = {
        deps.get_current_user: mock_user,
        deps.get_job_store: lambda: MockStore()
    }

    from backend.main import app
    app.dependency_overrides = app_overrides
    try:
        resp = client.post("/videos/jobs/missing/viral-metadata", headers=user_auth_headers)
        assert resp.status_code == 404
    finally:
         app.dependency_overrides = {}

def test_get_secret_path_not_exists(monkeypatch):
    """Cover path not exists in secret search (lines 328-329)."""
    # Force use file secrets
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "1")
    monkeypatch.setenv("GSP_SECRETS_FILE", "dummy.toml")

    # Mock path exists to return False first, then True
    original_exists = Path.exists

    def side_effect(self):
        if str(self) == "dummy.toml":
            return False
        return True # fallthrough to second path

    # We need to control both paths.
    # The function checks GSP_SECRETS_FILE then config/secrets.toml
    # We want dummy.toml -> False, then secrets.toml -> False (or True but empty)

    with patch("pathlib.Path.exists", return_value=False):
        # Both return False, so it hits 'continue' then returns None
        assert auth._get_secret("FOO") is None

def test_subtitles_progress_callbacks(monkeypatch, tmp_path):
    """Cover progress callbacks in OpenAITranscriber."""
    from backend.app.services.transcription.openai_cloud import OpenAITranscriber

    # Mock client
    mock_transcript = MagicMock()
    mock_transcript.segments = []

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_transcript

    monkeypatch.setattr("backend.app.services.transcription.openai_cloud._load_openai_client", lambda k: mock_client)
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    callback = MagicMock()

    p = tmp_path / "audio.wav"
    p.touch()

    t = OpenAITranscriber(api_key="key")
    t.transcribe(p, tmp_path, progress_callback=callback)

    assert callback.call_count >= 2 # 10.0 and 100.0 or 90.0

def test_short_cue_optimization():
    """Cover _split_long_cues short cue return (line 560)."""
    c = subtitles.Cue(0, 1, "Short")
    res = subtitles._split_long_cues([c], max_chars=100)
    assert len(res) == 1
    assert res[0] == c

def test_openai_api_key_resolve_none(monkeypatch):
    """Cover _resolve_openai_api_key returning None (line 304)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("pathlib.Path.exists", return_value=False):
        assert subtitles._resolve_openai_api_key() is None



def test_save_upload_limit_boundary(monkeypatch):
    """Cover upload limit boundary check (lines 68-70)."""
    # We need to test _save_upload_with_limit directly with a mocked UploadFile
    # that yields a chunk > limit (or cumulative > limit).

    import io

    from fastapi import HTTPException, UploadFile

    from backend.app.api.endpoints import videos

    # Mock settings
    monkeypatch.setattr("backend.app.api.endpoints.file_utils.MAX_UPLOAD_BYTES", 10) # 10 bytes limit

    # Create valid UploadFile
    # UploadFile takes a 'file' argument which is a SpooledTemporaryFile usually
    # We can pass an io.BytesIO
    data = b"0" * 20 # 20 bytes > 10
    f = io.BytesIO(data)
    upload = UploadFile(file=f, filename="test.mp4")

    dest = MagicMock()
    # Mock open context manager
    mock_buffer = MagicMock()
    dest.open.return_value.__enter__.return_value = mock_buffer

    try:
        videos._save_upload_with_limit(upload, dest)
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 413

    # Verify buffer closed and dest unlinked
    mock_buffer.close.assert_called()
    dest.unlink.assert_called()


def test_transcribe_with_openai_no_key(monkeypatch, tmp_path):
    """Cover OpenAITranscriber missing key."""
    from backend.app.services import subtitles
    from backend.app.services.transcription.openai_cloud import OpenAITranscriber

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Mock resolve to None
    monkeypatch.setattr(subtitles, "_resolve_openai_api_key", lambda *a: None)
    # Also patch local reference in openai_cloud if needed, but it imports from subtitles
    # which we mocked above via subtitles module.

    try:
        t = OpenAITranscriber()
        t.transcribe(tmp_path / "a.wav", tmp_path)
        assert False, "Should raise RuntimeError"
    except RuntimeError as e:
        assert "OpenAI API key is required" in str(e)

def test_wrap_lines_no_result():
    """Cover _wrap_lines empty wrapped (line 671)."""
    from backend.app.services import subtitles
    # If text is empty, textwrap returns [].
    # But if lines=[""], words=[""].
    res = subtitles._wrap_lines([""])
    assert res == [[""]]

def test_load_openai_client_no_key(monkeypatch):
    """Cover _load_openai_client missing key (line 858)."""
    from backend.app.services import subtitles
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(subtitles, "_resolve_openai_api_key", lambda *a: None)

    try:
        subtitles._load_openai_client(None)
        assert False
    except RuntimeError as e:
        assert "OpenAI API key is required" in str(e)

def test_generate_viral_metadata_no_key(monkeypatch):
    """Cover generate_viral_metadata missing key - SKIPPED: feature removed."""
    import pytest
    pytest.skip("generate_viral_metadata feature removed")
    from backend.app.services import subtitles
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(subtitles, "_resolve_openai_api_key", lambda *a: None)

    try:
        subtitles.generate_viral_metadata("transcript")
        assert False
    except RuntimeError as e:
        assert "OpenAI API key is required" in str(e)

def test_generate_viral_metadata_empty_response(monkeypatch):
    """Cover empty LLM response - SKIPPED: feature removed."""
    import pytest
    pytest.skip("generate_viral_metadata feature removed")
    from backend.app.services import subtitles

    monkeypatch.setenv("OPENAI_API_KEY", "key")

    class MockClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    class Choice:
                        class Message:
                            content = ""
                        message = Message()
                    class Resp:
                        choices = [Choice()]
                    return Resp()

    monkeypatch.setattr(subtitles, "_load_openai_client", lambda k: MockClient())

    try:
        subtitles.generate_viral_metadata("transcript")
        assert False
    except ValueError as e:
        assert "Empty response" in str(e) or "Failed to generate" in str(e)

def test_video_processing_turbo_alias(monkeypatch):
    """Cover turbo model alias (line 254-255)."""
    from backend.app.core import config
    from backend.app.services import video_processing

    # Track what model was passed to the transcriber
    captured_model = {}

    class MockTranscriber:
        def transcribe(self, audio_path, output_dir, language, model, **kwargs):
            captured_model["model"] = model
            srt_path = output_dir / "test.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n")
            return srt_path, []

    # Patch the LocalWhisperTranscriber (default provider for turbo model)
    monkeypatch.setattr(video_processing, "LocalWhisperTranscriber", lambda **kw: MockTranscriber())

    # Mock other pipeline steps
    monkeypatch.setattr(video_processing.subtitles, "extract_audio", lambda *a, **k: Path("a.wav"))
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", lambda *a, **k: Path("a.ass"))
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", lambda *a, **k: "")
    monkeypatch.setattr(video_processing, "_persist_artifacts", lambda *a: None)
    monkeypatch.setattr(video_processing.subtitles, "get_video_duration", lambda *a: 10.0)
    # Patch probe_media because normalize now calls it
    monkeypatch.setattr(video_processing, "probe_media", lambda p: video_processing.MediaProbe(duration_s=10.0, audio_codec="aac"))

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        in_p = p / "in.mp4"
        in_p.touch()
        out_p = p / "out.mp4"

        # We need to ensure out_p exists after "ffmpeg"
        out_p.touch()

        video_processing.normalize_and_stub_subtitles(
            in_p, out_p, model_size="turbo"
        )

        # Verify the turbo alias was resolved to config.WHISPER_MODEL
        assert captured_model["model"] == config.WHISPER_MODEL

def test_video_processing_artifact_same_path(monkeypatch):
    """Cover output path == artifact output path (line 480)."""
    from backend.app.services import video_processing

    # Mock pipeline steps
    monkeypatch.setattr(video_processing.subtitles, "extract_audio", lambda *a, **k: Path("a.wav"))
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", lambda *a, **k: (Path("a.srt"), []))
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", lambda *a, **k: Path("a.ass"))
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", lambda *a, **k: "")
    monkeypatch.setattr(video_processing, "_persist_artifacts", lambda *a: None)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td).resolve()
        artifact_dir = p / "artifacts"
        artifact_dir.mkdir()

        in_p = p / "in.mp4"
        in_p.touch()

        # Output IS inside artifact dir with same name
        out_p = artifact_dir / "out.mp4"

        # We need to ensure out_p exists after "ffmpeg"
        out_p.touch()

        # This function normally mkdirs parent of output which is artifact_dir (exists)
        # normalize... has logic:
        # video_copy = artifact_dir / destination.name
        # if destination != video_copy: separate copy
        # else: final_output = destination

        video_processing.normalize_and_stub_subtitles(
            in_p, out_p, artifact_dir=artifact_dir
        )
        # If it didn't crash and logic passed, we are good.
        # Coverage report will confirm line hit.





# ==========================================
# Auth Core Coverage (app/core/auth.py)
# ==========================================

def test_get_secret_file_exception(monkeypatch):
    """Cover exception reading secrets file (lines 333-334)."""
    # Force use file secrets
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "1")
    monkeypatch.setenv("GSP_SECRETS_FILE", "dummy.toml")

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", side_effect=Exception("Read error")):
            assert auth._get_secret("FOO") is None

def test_user_to_session():
    """Cover User.to_session (line 33)."""
    u = auth.User("1", "e", "n", "p")
    s = u.to_session()
    assert s["id"] == "1"
    assert s["email"] == "e"


# ==========================================
# Subtitles Coverage (app/services/subtitles.py)
# ==========================================

def test_resolve_openai_api_key_exception(monkeypatch):
    """Cover lines 301-304 (exception reading secrets)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Mock file exists but open fails
    with patch("pathlib.Path.exists", return_value=True):
         with patch("builtins.open", side_effect=Exception("Read fail")):
             assert subtitles._resolve_openai_api_key() is None

def test_format_karaoke_fallback_empty():
    """Cover line 715 (empty wrapped lines in fallback)."""
    # If text is empty or just whitespace?
    cue = subtitles.Cue(0, 1, "   ")
    res = subtitles._format_karaoke_text(cue)
    assert res == ""
