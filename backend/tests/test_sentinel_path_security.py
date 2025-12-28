import pytest
from pathlib import Path
from fastapi import HTTPException, UploadFile
from backend.app.api.endpoints import file_utils
import shutil
import io

def test_validate_path_is_safe_success(tmp_path):
    base_dir = tmp_path / "safe"
    base_dir.mkdir()
    target_path = base_dir / "file.txt"

    # Should not raise
    file_utils.validate_path_is_safe(target_path, base_dir)

def test_validate_path_is_safe_traversal(tmp_path):
    base_dir = tmp_path / "safe"
    base_dir.mkdir()

    # Attempt to go up one level
    target_path = base_dir / "../file.txt"

    with pytest.raises(HTTPException) as exc:
        file_utils.validate_path_is_safe(target_path, base_dir)
    assert exc.value.status_code == 400
    assert "Invalid path" in exc.value.detail

def test_validate_path_is_safe_symlink_attack(tmp_path):
    base_dir = tmp_path / "safe"
    base_dir.mkdir()
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()

    # Create a symlink in base_dir pointing to secret_dir
    symlink = base_dir / "link"
    try:
        symlink.symlink_to(secret_dir)
    except OSError:
        pytest.skip("Symlinks not supported")

    target_path = symlink / "file.txt"

    # This should fail because it resolves to outside base_dir
    with pytest.raises(HTTPException) as exc:
        file_utils.validate_path_is_safe(target_path, base_dir)
    assert exc.value.status_code == 400

def test_save_upload_with_limit_safe_path(tmp_path, monkeypatch):
    # Mock settings.data_dir to point to tmp_path
    monkeypatch.setattr(file_utils.settings, "data_dir", tmp_path)

    content = b"test content"
    upload = UploadFile(filename="test.txt", file=io.BytesIO(content))

    # Valid destination inside tmp_path
    dest = tmp_path / "uploads" / "test.txt"

    # Ensure save_upload_with_limit calls validate_path_is_safe, which uses settings.data_dir (tmp_path)
    # So this should succeed
    file_utils.save_upload_with_limit(upload, dest)

    assert dest.exists()
    assert dest.read_bytes() == content

def test_save_upload_with_limit_unsafe_path(tmp_path, monkeypatch):
    # Mock settings.data_dir to point to tmp_path
    monkeypatch.setattr(file_utils.settings, "data_dir", tmp_path)

    content = b"test content"
    upload = UploadFile(filename="test.txt", file=io.BytesIO(content))

    # Attempt to write outside tmp_path
    # We need a path that resolves to outside tmp_path
    # ../outside.txt
    dest = tmp_path / ".." / "outside.txt"

    with pytest.raises(HTTPException) as exc:
        file_utils.save_upload_with_limit(upload, dest)
    assert exc.value.status_code == 400
