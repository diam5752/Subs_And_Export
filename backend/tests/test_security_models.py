import pytest
from pydantic import ValidationError

from backend.app.api.endpoints.auth import UserUpdatePassword
from backend.app.api.endpoints.tiktok import TikTokUploadRequest
from backend.app.api.endpoints.videos import (
    ExportRequest,
    TranscriptionCueRequest,
    TranscriptionWordRequest,
)
from backend.app.schemas.base import BatchDeleteRequest



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


def test_transcription_request_limits():
    # Verify word limit (100) - stricter limit from sentinel fix
    with pytest.raises(ValidationError):
        TranscriptionWordRequest(start=0.0, end=1.0, text="a" * 101)

    # Verify cue limit (2000)
    with pytest.raises(ValidationError):
        TranscriptionCueRequest(start=0.0, end=1.0, text="a" * 2001)


def test_tiktok_request_limits():
    huge_string = "a" * 2201

    with pytest.raises(ValidationError):
        TikTokUploadRequest(
            access_token="valid",
            video_path="valid",
            title=huge_string,
            description="valid",
        )

    with pytest.raises(ValidationError):
        TikTokUploadRequest(
            access_token="valid",
            video_path="valid",
            title="valid",
            description=huge_string,
        )

    with pytest.raises(ValidationError):
        TikTokUploadRequest(
            access_token="a" * 4097,
            video_path="valid",
            title="valid",
            description="valid",
        )


def test_batch_delete_request_limits():
    # Verify job_ids limit (64 chars)
    valid_id = "a" * 64
    # Ensure valid passes
    BatchDeleteRequest(job_ids=[valid_id])

    with pytest.raises(ValidationError):
        BatchDeleteRequest(job_ids=["a" * 65])
