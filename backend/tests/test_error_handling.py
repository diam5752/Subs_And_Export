import subprocess

from backend.app.core.errors import sanitize_error


def test_sanitize_value_error():
    e = ValueError("Invalid input")
    assert sanitize_error(e) == "Invalid input"

def test_sanitize_permission_error():
    e = PermissionError("Access denied")
    assert sanitize_error(e) == "Access denied"

def test_sanitize_subprocess_error_no_stderr():
    e = subprocess.CalledProcessError(1, ["ls"])
    assert sanitize_error(e) == "Process failed with exit code 1."

def test_sanitize_subprocess_error_with_safe_stderr():
    e = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="Some info\nInvalid data found when processing input\nMore info")
    assert "Invalid video data" in sanitize_error(e)

def test_sanitize_subprocess_error_with_unsafe_stderr():
    e = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="Error opening /secret/path/file.mp4")
    # Should not contain the path
    msg = sanitize_error(e)
    assert "/secret/path" not in msg
    assert msg == "Process failed with exit code 1."

def test_sanitize_generic_exception():
    e = KeyError("secret_key")
    # Should return generic message
    assert sanitize_error(e) == "An internal error occurred"

    assert sanitize_error(e, "Custom generic") == "Custom generic"
