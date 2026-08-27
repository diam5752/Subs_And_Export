"""Short-lived, artifact-scoped download grant regressions."""

from __future__ import annotations

import pytest

from backend.app.core.download_grants import (
    DownloadGrantError,
    create_download_grant,
    validate_download_grant,
)

SECRET = "g" * 64
FILE_PATH = "artifacts/job-123/processed_720x1280.mp4"


def test_download_grant_round_trip_is_bound_to_exact_claims() -> None:
    token = create_download_grant(
        secret=SECRET,
        user_id="user-123",
        file_path=FILE_PATH,
        filename="Δοκιμή_subs.mp4",
        ttl_seconds=300,
        now=1_800_000_000,
    )

    claims = validate_download_grant(
        token,
        secret=SECRET,
        expected_file_path=FILE_PATH,
        ttl_seconds=300,
        now=1_800_000_120,
    )

    assert claims.user_id == "user-123"
    assert claims.file_path == FILE_PATH
    assert claims.filename == "Δοκιμή_subs.mp4"
    assert claims.expires_at == 1_800_000_300


@pytest.mark.parametrize(
    "mutation",
    [
        lambda token: f"{token[:-1]}{'a' if token[-1] != 'a' else 'b'}",
        lambda token: f"x{token[1:]}",
        lambda token: token + ".extra",
        lambda _token: "not-a-grant",
        lambda _token: "💥.invalid",
    ],
)
def test_download_grant_rejects_tampering_and_malformed_tokens(mutation) -> None:
    token = create_download_grant(
        secret=SECRET,
        user_id="user-123",
        file_path=FILE_PATH,
        filename="video.mp4",
        ttl_seconds=300,
        now=1_800_000_000,
    )

    with pytest.raises(DownloadGrantError):
        validate_download_grant(
            mutation(token),
            secret=SECRET,
            expected_file_path=FILE_PATH,
            ttl_seconds=300,
            now=1_800_000_010,
        )


def test_download_grant_rejects_expiry_and_a_different_artifact() -> None:
    token = create_download_grant(
        secret=SECRET,
        user_id="user-123",
        file_path=FILE_PATH,
        filename="video.mp4",
        ttl_seconds=300,
        now=1_800_000_000,
    )

    with pytest.raises(DownloadGrantError, match="expired"):
        validate_download_grant(
            token,
            secret=SECRET,
            expected_file_path=FILE_PATH,
            ttl_seconds=300,
            now=1_800_000_300,
        )
    with pytest.raises(DownloadGrantError, match="artifact"):
        validate_download_grant(
            token,
            secret=SECRET,
            expected_file_path="artifacts/job-123/processed_1080x1920.mp4",
            ttl_seconds=300,
            now=1_800_000_010,
        )


def test_download_grant_rejects_short_secrets_and_noncanonical_claims() -> None:
    with pytest.raises(DownloadGrantError, match="secret"):
        create_download_grant(
            secret="short",
            user_id="user-123",
            file_path=FILE_PATH,
            filename="video.mp4",
            ttl_seconds=300,
        )
    with pytest.raises(DownloadGrantError, match="path"):
        create_download_grant(
            secret=SECRET,
            user_id="user-123",
            file_path="artifacts/job-123/../private.mp4",
            filename="video.mp4",
            ttl_seconds=300,
        )


def test_download_grant_supports_utf8_artifact_names() -> None:
    utf8_path = "artifacts/job-123/δοκιμή.mp4"
    token = create_download_grant(
        secret=SECRET,
        user_id="user-123",
        file_path=utf8_path,
        filename="δοκιμή_subs.mp4",
        ttl_seconds=300,
        now=1_800_000_000,
    )

    claims = validate_download_grant(
        token,
        secret=SECRET,
        expected_file_path=utf8_path,
        ttl_seconds=300,
        now=1_800_000_001,
    )

    assert claims.file_path == utf8_path
