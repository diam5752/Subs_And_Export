
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock
from backend.app.common.cleanup import cleanup_old_jobs

def test_cleanup_removes_old_files(tmp_path):
    """Test that files older than retention are deleted."""
    uploads = tmp_path / "uploads"
    artifacts = tmp_path / "artifacts"
    uploads.mkdir()
    artifacts.mkdir()
    
    # Old file
    old_file = uploads / "old.mp4"
    old_file.touch()
    
    # Make it look old (25 hours ago)
    past = time.time() - (25 * 3600)
    import os
    os.utime(old_file, (past, past))
    
    # New file
    new_file = uploads / "new.mp4"
    new_file.touch()
    
    # Old directory
    old_dir = artifacts / "old_job"
    old_dir.mkdir()
    os.utime(old_dir, (past, past))
    
    cleanup_old_jobs(uploads, artifacts, retention_hours=24)
    
    assert not old_file.exists()
    assert new_file.exists()
    assert not old_dir.exists()

def test_cleanup_skips_gitkeep(tmp_path):
    """Test that .gitkeep is preserved."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    
    gitkeep = uploads / ".gitkeep"
    gitkeep.touch()
    
    # Make it old
    past = time.time() - (100 * 3600)
    import os
    os.utime(gitkeep, (past, past))
    
    cleanup_old_jobs(uploads, tmp_path / "artifacts", retention_hours=1)
    
    assert gitkeep.exists()

def test_cleanup_race_condition(tmp_path, monkeypatch):
    """Test handling of race condition where file vanishes."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    f = uploads / "race.mp4"
    f.touch()
    
    # Make it old
    past = time.time() - (25 * 3600)
    import os
    os.utime(f, (past, past))
    
    # Mock check_and_delete logic implicitly by mocking path.exists
    # But cleanup iterates first.
    # We can mock Path.exists to return True first (iter) then False (check).
    # Easier: Mock unlink to raise FileNotFoundError (simulating race)
    
    def mock_unlink(*args, **kwargs):
        raise FileNotFoundError("Gone")
        
    monkeypatch.setattr(Path, "unlink", mock_unlink)
    
    # Should not raise
    cleanup_old_jobs(uploads, tmp_path / "artifacts", retention_hours=24)

def test_cleanup_exception(tmp_path, monkeypatch):
    """Test general exception handling during cleanup."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    f = uploads / "error.mp4"
    f.touch()
    
    past = time.time() - (25 * 3600)
    import os
    os.utime(f, (past, past))
    
    def mock_unlink(*args, **kwargs):
        raise PermissionError("Access denied")
        
    monkeypatch.setattr(Path, "unlink", mock_unlink)
    
    # Should log error but not crash
    cleanup_old_jobs(uploads, tmp_path / "artifacts", retention_hours=24)
