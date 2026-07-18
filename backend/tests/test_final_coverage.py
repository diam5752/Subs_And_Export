from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.api.endpoints import export_routes, file_utils
from backend.app.api.endpoints.settings import parse_resolution
from backend.app.core import auth, cleanup
from backend.app.services import llm_utils, subtitles

# ==========================================
# Videos Endpoint Coverage (app/api/endpoints/videos.py)
# ==========================================

def test_parse_resolution_error():
    """Cover exception path in _parse_resolution (lines 106-107)."""
    assert parse_resolution("100xInvalid") == (None, None)

def test_ensure_job_size_exception():
    """Cover exception path in _ensure_job_size (lines 328-329)."""
    # Create a job with a path that exists but stat() fails
    mock_job = MagicMock()
    mock_job.status = "completed"
    mock_job.result_data = {"video_path": "foo.mp4"}

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.stat", side_effect=Exception("Stat failed")):
             # Should safe catch
             export_routes._ensure_job_size(mock_job)

# ==========================================
# Cleanup Coverage (app/core/cleanup.py)
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

    with patch("backend.app.core.cleanup.Path.iterdir", return_value=[mock_path]):
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

    monkeypatch.setattr("backend.app.services.transcription.openai_cloud.load_openai_client", lambda k: mock_client)
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
    res = subtitles.subtitle_renderer.split_long_cues([c], max_chars=100)
    assert len(res) == 1
    assert res[0] == c

def test_openai_api_key_resolve_none(monkeypatch):
    """Cover _resolve_openai_api_key returning None (line 304)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("pathlib.Path.exists", return_value=False):
        assert llm_utils.resolve_openai_api_key() is None



def test_save_upload_limit_boundary(monkeypatch):
    """Cover upload limit boundary check (lines 68-70)."""
    # We need to test _save_upload_with_limit directly with a mocked UploadFile
    # that yields a chunk > limit (or cumulative > limit).

    import io

    from fastapi import HTTPException, UploadFile

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
        file_utils.save_upload_with_limit(upload, dest)
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 413

    # Verify buffer closed and dest unlinked
    mock_buffer.close.assert_called()
    dest.unlink.assert_called()


def test_transcribe_with_openai_no_key(monkeypatch, tmp_path):
    """Cover OpenAITranscriber missing key."""
    from backend.app.services.transcription.openai_cloud import OpenAITranscriber

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Mock resolve to None
    monkeypatch.setattr("backend.app.services.llm_utils.resolve_openai_api_key", lambda *a: None)
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
    res = subtitles.subtitle_renderer.wrap_lines([""])
    assert res == [[""]]

def test_load_openai_client_no_key(monkeypatch):
    """Cover _load_openai_client missing key (line 858)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("backend.app.services.llm_utils.resolve_openai_api_key", lambda *a: None)

    try:
        llm_utils.load_openai_client(None)
        assert False
    except Exception as e:
        assert "api_key" in str(e) or "required" in str(e)

def test_video_processing_artifact_same_path(monkeypatch):
    """Cover output path == artifact output path (line 480)."""
    from backend.app.services import video_processing

    # Mock pipeline steps
    class MockTranscriber:
        def transcribe(self, *args, **kwargs):
            return Path("a.srt"), []

    monkeypatch.setattr(video_processing, "GroqTranscriber", lambda: MockTranscriber())
    monkeypatch.setattr(video_processing.llm_utils, "resolve_groq_api_key", lambda: "test-groq-key")
    monkeypatch.setattr("backend.app.services.ffmpeg_utils.probe_media", lambda p: video_processing.ffmpeg_utils.MediaProbe(duration_s=10.0, audio_codec="aac"))
    monkeypatch.setattr(video_processing.subtitles, "extract_audio", lambda *a, **k: Path("a.wav"))
    monkeypatch.setattr(video_processing.subtitles, "generate_subtitles_from_audio", lambda *a, **k: (Path("a.srt"), []))
    monkeypatch.setattr(video_processing.subtitles, "create_styled_subtitle_file", lambda *a, **k: Path("a.ass"))
    monkeypatch.setattr(video_processing.ffmpeg_utils, "run_ffmpeg_with_subs", lambda *a, **k: "")
    monkeypatch.setattr(video_processing.artifact_manager, "persist_artifacts", lambda *a, **kw: None)

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
             assert llm_utils.resolve_openai_api_key() is None

def test_format_karaoke_fallback_empty():
    """Cover line 715 (empty wrapped lines in fallback)."""
    # If text is empty or just whitespace?
    cue = subtitles.Cue(0, 1, "   ")
    res = subtitles.subtitle_renderer.format_karaoke_text(cue)
    assert res == ""
