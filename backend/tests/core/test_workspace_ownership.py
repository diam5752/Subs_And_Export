from __future__ import annotations

import stat
from pathlib import Path

import pytest

from backend.app.core.workspace_ownership import (
    WorkspaceOwnershipConflictError,
    get_workspace_owner,
    list_owned_workspace_ids,
    list_workspace_ownership_markers,
    record_workspace_ownership,
    remove_workspace_ownership_after_verified_cleanup,
)


def test_workspace_ownership_marker_is_private_canonical_and_idempotent(
    tmp_path: Path,
) -> None:
    first = record_workspace_ownership(
        data_dir=tmp_path,
        job_id="job-1",
        user_id="user-1",
        now=1_800_000_000,
    )
    second = record_workspace_ownership(
        data_dir=tmp_path,
        job_id="job-1",
        user_id="user-1",
        now=1_800_000_001,
    )

    assert second == first
    assert list_owned_workspace_ids(data_dir=tmp_path, user_id="user-1") == [
        "job-1",
    ]
    assert get_workspace_owner(data_dir=tmp_path, job_id="job-1") == "user-1"
    registry = tmp_path / ".workspace-ownership"
    marker_files = [path for path in registry.glob("*.json")]
    assert len(marker_files) == 1
    assert "job-1" not in marker_files[0].name
    assert stat.S_IMODE(registry.stat().st_mode) == 0o700
    assert stat.S_IMODE(marker_files[0].stat().st_mode) == 0o600

    assert remove_workspace_ownership_after_verified_cleanup(
        data_dir=tmp_path,
        job_id="job-1",
        expected_user_id="user-1",
    )
    assert not remove_workspace_ownership_after_verified_cleanup(
        data_dir=tmp_path,
        job_id="job-1",
        expected_user_id="user-1",
    )
    assert get_workspace_owner(data_dir=tmp_path, job_id="job-1") is None


def test_workspace_ownership_rejects_cross_account_reassignment(
    tmp_path: Path,
) -> None:
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id="shared-job",
        user_id="first-user",
    )

    with pytest.raises(
        WorkspaceOwnershipConflictError,
        match="another account",
    ):
        record_workspace_ownership(
            data_dir=tmp_path,
            job_id="shared-job",
            user_id="second-user",
        )
    with pytest.raises(
        WorkspaceOwnershipConflictError,
        match="changed before cleanup",
    ):
        remove_workspace_ownership_after_verified_cleanup(
            data_dir=tmp_path,
            job_id="shared-job",
            expected_user_id="second-user",
        )

    assert get_workspace_owner(data_dir=tmp_path, job_id="shared-job") == ("first-user")


def test_registry_scavenges_only_exact_regular_crash_temp_files(
    tmp_path: Path,
) -> None:
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id="job-1",
        user_id="user-1",
    )
    registry = tmp_path / ".workspace-ownership"
    digest = "a" * 64
    stale_temp = registry / f".{digest}.json.{'b' * 32}.tmp"
    unknown_hidden = registry / ".keep-this-unknown"
    symlink_temp = registry / f".{digest}.json.{'c' * 32}.tmp"
    symlink_target = tmp_path / "outside"
    stale_temp.write_bytes(b"crash residue")
    unknown_hidden.write_bytes(b"not ours")
    symlink_target.write_bytes(b"outside")
    symlink_temp.symlink_to(symlink_target)

    assert list_owned_workspace_ids(data_dir=tmp_path, user_id="user-1") == [
        "job-1",
    ]

    assert not stale_temp.exists()
    assert unknown_hidden.read_bytes() == b"not ours"
    assert symlink_temp.is_symlink()
    assert symlink_target.read_bytes() == b"outside"


def test_workspace_ownership_marker_listing_is_bounded_and_cursor_paginated(
    tmp_path: Path,
) -> None:
    expected = {f"job-{index}": 1_800_000_000 + index for index in range(3)}
    for job_id, created_at in expected.items():
        record_workspace_ownership(
            data_dir=tmp_path,
            job_id=job_id,
            user_id="user-1",
            now=created_at,
        )

    first = list_workspace_ownership_markers(data_dir=tmp_path, limit=2)
    assert len(first.markers) == 2
    assert first.next_cursor is not None
    second = list_workspace_ownership_markers(
        data_dir=tmp_path,
        limit=2,
        after=first.next_cursor,
    )

    assert len(second.markers) == 1
    assert second.next_cursor is None
    assert {marker.job_id: marker.created_at for marker in [*first.markers, *second.markers]} == expected

    with pytest.raises(ValueError, match="limit"):
        list_workspace_ownership_markers(data_dir=tmp_path, limit=0)
    with pytest.raises(ValueError, match="cursor"):
        list_workspace_ownership_markers(
            data_dir=tmp_path,
            after="not-a-marker-cursor",
        )
