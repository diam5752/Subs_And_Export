import subprocess

from backend.app.core.errors import sanitize_error


def test_sanitize_error_strips_internal_paths():
    """Test that internal paths are replaced with [INTERNAL_PATH]."""
    # Test typical Unix paths
    error_msg = "Error opening file /app/backend/data/uploads/123.mp4"
    sanitized = sanitize_error(ValueError(error_msg))
    assert "[INTERNAL_PATH]" in sanitized
    assert "/app/backend/data" not in sanitized

    # Test nested paths
    error_msg = "Permission denied: /home/user/project/file.txt"
    sanitized = sanitize_error(ValueError(error_msg))
    assert "[INTERNAL_PATH]" in sanitized
    assert "/home/user" not in sanitized

def test_sanitize_error_subprocess():
    """Test that subprocess.CalledProcessError hides command args."""
    cmd = ["ffmpeg", "-i", "/app/data/input.mp4", "/app/data/output.mp4"]
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=cmd,
        output="Conversion failed!"
    )

    sanitized = sanitize_error(error)
    assert "Processing command failed with exit code 1" in sanitized
    assert "ffmpeg" not in sanitized
    assert "/app/data/input.mp4" not in sanitized
    assert "Conversion failed!" not in sanitized

def test_sanitize_error_safe_exceptions():
    """Test that safe exceptions (ValueError) are passed through (but sanitized)."""
    error = ValueError("Invalid resolution 100x100")
    sanitized = sanitize_error(error)
    assert "Invalid resolution 100x100" == sanitized

    # Even safe exceptions should have paths stripped
    error_path = ValueError("File /tmp/bad not found")
    sanitized_path = sanitize_error(error_path)
    assert "[INTERNAL_PATH]" in sanitized_path
    assert "/tmp/bad" not in sanitized_path

def test_sanitize_error_unknown_exception():
    """Test that unknown exceptions are masked."""
    error = KeyError("Missing config key")
    sanitized = sanitize_error(error)
    assert "An internal error occurred" == sanitized
    assert "Missing config key" not in sanitized

def test_sanitize_error_string_input():
    """Test that string inputs are sanitized directly."""
    msg = "Failed at /var/log/syslog"
    sanitized = sanitize_error(msg)
    assert "Failed at [INTERNAL_PATH]" == sanitized
