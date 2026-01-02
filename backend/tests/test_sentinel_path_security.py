
import os
import pytest
from pathlib import Path
from backend.app.api.endpoints.file_utils import validate_path_is_safe

def test_validate_path_is_safe_valid(tmp_path):
    """Test that a valid path inside the base directory is accepted."""
    base = tmp_path / "base"
    base.mkdir()
    child = base / "child.txt"
    child.touch()

    result = validate_path_is_safe(child, base)
    assert result == child.resolve()

def test_validate_path_is_safe_traversal(tmp_path):
    """Test that path traversal attempts are blocked."""
    base = tmp_path / "base"
    base.mkdir()

    # Attempt to go up
    unsafe = base / ".." / "outside.txt"

    with pytest.raises(ValueError, match="Path traversal detected"):
        validate_path_is_safe(unsafe, base)

def test_validate_path_is_safe_symlink_attack(tmp_path):
    """Test that a symlink pointing outside the base directory is blocked."""
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "secret.txt"
    outside.touch()

    link = base / "link_to_secret"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    # The link itself is inside base, but it resolves to outside
    with pytest.raises(ValueError, match="Path traversal detected"):
        validate_path_is_safe(link, base)

def test_validate_path_is_safe_nonexistent_inside(tmp_path):
    """Test that non-existent paths are allowed if they WOULD be inside."""
    base = tmp_path / "base"
    base.mkdir()
    target = base / "new_file.txt"

    # This should pass because the resolved path is inside base
    result = validate_path_is_safe(target, base)
    assert result == target.resolve()

def test_validate_path_is_safe_absolute_outside(tmp_path):
    """Test that an absolute path outside base is blocked."""
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "other"

    with pytest.raises(ValueError, match="Path traversal detected"):
        validate_path_is_safe(outside, base)
