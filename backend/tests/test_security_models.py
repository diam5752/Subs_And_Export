
import pytest
from pydantic import ValidationError

from backend.app.api.endpoints.auth import UserUpdatePassword
from backend.app.api.endpoints.videos import ExportRequest, TranscriptionCueRequest, TranscriptionWordRequest


def test_user_update_password_length_limits():
    huge_string = "a" * 129

    # Verify password limit (existing)
    with pytest.raises(ValidationError):
        UserUpdatePassword(password=huge_string, confirm_password="a")

    # Verify confirm_password limit is enforced
    with pytest.raises(ValidationError):
        UserUpdatePassword(password="valid1234567", confirm_password=huge_string)

def test_export_request_length_limits():
    huge_string = "a" * 100

    with pytest.raises(ValidationError):
        ExportRequest(resolution=huge_string)

    with pytest.raises(ValidationError):
        ExportRequest(resolution="1080x1920", subtitle_color=huge_string)

    with pytest.raises(ValidationError):
        ExportRequest(resolution="1080x1920", highlight_style=huge_string)

def test_transcription_request_length_limits():
    huge_string = "a" * 2001

    with pytest.raises(ValidationError):
        TranscriptionCueRequest(start=0, end=1, text=huge_string)

    with pytest.raises(ValidationError):
        TranscriptionWordRequest(start=0, end=1, text="a" * 101)
