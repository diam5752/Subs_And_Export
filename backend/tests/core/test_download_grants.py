"""Short-lived, artifact-scoped download grant regressions."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from backend.app.core import download_grants
from backend.app.core.download_grants import (
    DownloadGrantError,
    create_download_grant,
    validate_download_grant,
)

SECRET = "g" * 64
FILE_PATH = "artifacts/job-123/processed_720x1280.mp4"


def _signed_payload(payload: object | str) -> str:
    raw = (
        payload
        if isinstance(payload, str)
        else json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    encoded = download_grants._encode_base64url(raw.encode("utf-8"))
    signature = hmac.new(
        SECRET.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{download_grants._encode_base64url(signature)}"


def _valid_payload() -> dict[str, object]:
    return {
        "exp": 1_300,
        "iat": 1_000,
        "name": "video.mp4",
        "path": FILE_PATH,
        "uid": "user-123",
        "v": 1,
    }


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


@pytest.mark.parametrize("ttl", [True, 59, 601, 60.5])
def test_download_grant_rejects_invalid_ttl_types_and_bounds(ttl) -> None:
    with pytest.raises(DownloadGrantError, match="TTL"):
        create_download_grant(
            secret=SECRET,
            user_id="user-123",
            file_path=FILE_PATH,
            filename="video.mp4",
            ttl_seconds=ttl,
        )


@pytest.mark.parametrize(
    "file_path",
    ["", "artifacts\\job\\video.mp4", "artifacts/job", "private/job/video.mp4", "artifacts//video.mp4"],
)
def test_download_grant_rejects_every_noncanonical_path_shape(file_path: str) -> None:
    with pytest.raises(DownloadGrantError, match="path"):
        create_download_grant(
            secret=SECRET,
            user_id="user-123",
            file_path=file_path,
            filename="video.mp4",
            ttl_seconds=300,
        )


@pytest.mark.parametrize("issued_at", [True, -1, 1.5])
def test_download_grant_rejects_invalid_issue_times(issued_at) -> None:
    with pytest.raises(DownloadGrantError, match="issue time"):
        create_download_grant(
            secret=SECRET,
            user_id="user-123",
            file_path=FILE_PATH,
            filename="video.mp4",
            ttl_seconds=300,
            now=issued_at,
        )


def test_download_grant_rejects_empty_encoding_and_duplicate_json_keys() -> None:
    valid = _signed_payload(_valid_payload())
    encoded, _signature = valid.split(".", 1)
    with pytest.raises(DownloadGrantError, match="encoding"):
        validate_download_grant(
            f"{encoded}.",
            secret=SECRET,
            expected_file_path=FILE_PATH,
            ttl_seconds=300,
            now=1_001,
        )

    duplicate = f'{{"exp":1300,"iat":1000,"name":"video.mp4","path":"{FILE_PATH}","uid":"first","uid":"second","v":1}}'
    with pytest.raises(DownloadGrantError, match="payload"):
        validate_download_grant(
            _signed_payload(duplicate),
            secret=SECRET,
            expected_file_path=FILE_PATH,
            ttl_seconds=300,
            now=1_001,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: [payload], "payload"),
        (lambda payload: {key: value for key, value in payload.items() if key != "name"}, "payload"),
        (lambda payload: {**payload, "v": 2}, "version"),
        (lambda payload: {**payload, "iat": True}, "timing"),
        (lambda payload: {**payload, "exp": "1300"}, "timing"),
        (lambda payload: {**payload, "exp": 1_301}, "timing"),
        (lambda payload: {**payload, "uid": 123}, "claims"),
    ],
)
def test_download_grant_rejects_signed_but_invalid_claim_sets(mutate, message: str) -> None:
    with pytest.raises(DownloadGrantError, match=message):
        validate_download_grant(
            _signed_payload(mutate(_valid_payload())),
            secret=SECRET,
            expected_file_path=FILE_PATH,
            ttl_seconds=300,
            now=1_001,
        )


@pytest.mark.parametrize(("now", "message"), [(True, "current time"), (-1, "current time"), (900, "not active")])
def test_download_grant_rejects_invalid_or_premature_validation_time(now, message: str) -> None:
    with pytest.raises(DownloadGrantError, match=message):
        validate_download_grant(
            _signed_payload(_valid_payload()),
            secret=SECRET,
            expected_file_path=FILE_PATH,
            ttl_seconds=300,
            now=now,
        )


@pytest.mark.parametrize(("user_id", "filename"), [("", "video.mp4"), ("user", "bad\x00name.mp4")])
def test_download_grant_rejects_empty_or_control_character_claims(
    user_id: str,
    filename: str,
) -> None:
    with pytest.raises(DownloadGrantError, match="invalid"):
        create_download_grant(
            secret=SECRET,
            user_id=user_id,
            file_path=FILE_PATH,
            filename=filename,
            ttl_seconds=300,
        )
