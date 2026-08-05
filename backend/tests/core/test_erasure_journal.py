from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from backend.app.core import erasure_journal as journal_module
from backend.app.core.erasure_journal import (
    ErasureJournal,
    ErasureJournalError,
)


def test_journal_append_is_durable_private_and_canonical(tmp_path: Path) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)

    appended = journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-b", "job-a", "job-a"],
        now=1_800_000_000,
    )

    assert appended.job_ids == ["job-a", "job-b"]
    assert journal.read_all() == [appended]
    assert stat.S_IMODE(journal.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(journal.journal_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(journal.lock_path.stat().st_mode) == 0o600


def test_journal_requires_matching_live_volume_continuity(tmp_path: Path) -> None:
    continuity_id = "a" * 64
    root = tmp_path / "journal"
    journal = ErasureJournal(
        root,
        retention_days=30,
        expected_continuity_id=continuity_id,
    )

    with pytest.raises(ErasureJournalError, match="continuity is unavailable"):
        journal.read_all()

    journal.continuity_path.write_text(f"{continuity_id}\n", encoding="ascii")
    assert journal.read_all() == []

    journal.continuity_path.write_text(f"{'b' * 64}\n", encoding="ascii")
    with pytest.raises(ErasureJournalError, match="does not match this host"):
        journal.read_all()


def test_journal_rejects_symlinked_continuity_marker(tmp_path: Path) -> None:
    continuity_id = "c" * 64
    root = tmp_path / "journal"
    root.mkdir()
    target = tmp_path / "outside-marker"
    target.write_text(continuity_id, encoding="ascii")
    (root / ".continuity-id").symlink_to(target)
    journal = ErasureJournal(
        root,
        retention_days=30,
        expected_continuity_id=continuity_id,
    )

    with pytest.raises(ErasureJournalError, match="continuity is unavailable"):
        journal.read_all()


def test_provider_tombstone_contains_only_opaque_deletion_coordinates(
    tmp_path: Path,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)

    appended = journal.append_provider_transcript(
        provider="elevenlabs",
        transcript_id="opaque-transcript_123",
        now=1_800_000_000,
    )

    assert journal.read_all() == [appended]
    raw = json.loads(journal.journal_path.read_text(encoding="utf-8"))
    assert set(raw) == {
        "schema_version",
        "event_id",
        "kind",
        "created_at",
        "provider",
        "transcript_id",
    }
    assert raw["provider"] == "elevenlabs"
    assert raw["transcript_id"] == "opaque-transcript_123"
    assert "user_id" not in raw
    assert "job_ids" not in raw


def test_provider_tombstone_rejects_non_opaque_identifier(tmp_path: Path) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)

    with pytest.raises(ErasureJournalError, match="transcript identifier"):
        journal.append_provider_transcript(
            provider="elevenlabs",
            transcript_id="customer@example.com/transcript text",
            now=1_800_000_000,
        )


def test_orphan_workspace_tombstone_contains_only_exact_job_ids(
    tmp_path: Path,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)

    appended = journal.append_orphan_workspace(
        job_ids=["orphan-b", "orphan-a", "orphan-a"],
        now=1_800_000_000,
    )

    assert appended.job_ids == ["orphan-a", "orphan-b"]
    assert journal.read_all() == [appended]
    raw = json.loads(journal.journal_path.read_text(encoding="utf-8"))
    assert set(raw) == {
        "schema_version",
        "event_id",
        "kind",
        "created_at",
        "job_ids",
    }
    assert "user_id" not in raw


def test_journal_rejects_malformed_incomplete_and_oversized_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.root.mkdir(mode=0o700)

    journal.journal_path.write_bytes(b'{"schema_version":1')
    with pytest.raises(ErasureJournalError, match="incomplete record"):
        journal.read_all()

    monkeypatch.setattr(journal_module, "MAX_TOMBSTONE_BYTES", 32)
    journal.journal_path.write_bytes((b"x" * 33) + b"\n")
    with pytest.raises(ErasureJournalError, match="oversized record"):
        journal.read_all()


def test_journal_refuses_append_on_corrupt_or_full_existing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.root.mkdir(mode=0o700)
    journal.journal_path.write_bytes(b'{"schema_version":1')

    with pytest.raises(ErasureJournalError, match="incomplete record"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-1"],
            now=1_800_000_000,
        )

    journal.journal_path.unlink()
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-1"],
        now=1_800_000_000,
    )
    monkeypatch.setattr(
        journal_module,
        "MAX_JOURNAL_BYTES",
        journal.journal_path.stat().st_size + 1,
    )

    with pytest.raises(ErasureJournalError, match="safe size limit"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-2"],
            now=1_800_000_001,
        )


def test_journal_fsync_failure_blocks_erasure_intent_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(ErasureJournalError, match="stored durably"):
        journal.append(
            kind="workspace",
            user_id="user-1",
            job_ids=["job-1"],
            now=1_800_000_000,
        )


def test_journal_prunes_only_records_older_than_backup_safe_retention(
    tmp_path: Path,
) -> None:
    retention_days = 30
    now = 1_800_000_000
    cutoff = now - (retention_days * 86_400)
    journal = ErasureJournal(tmp_path / "journal", retention_days=retention_days)
    expired = journal.append(
        kind="workspace",
        user_id="user-1",
        job_ids=["expired-job"],
        now=cutoff - 1,
    )
    boundary = journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["boundary-job"],
        now=cutoff,
    )
    current = journal.append(
        kind="account",
        user_id="user-1",
        job_ids=[],
        now=now,
    )

    assert journal.prune_expired(now=now) == 1
    assert journal.read_all() == [boundary, current]
    assert expired not in journal.read_all()


def test_journal_rejects_symlink_directory(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    journal = ErasureJournal(linked_directory, retention_days=30)

    with pytest.raises(ErasureJournalError, match="cannot be a symlink"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-1"],
            now=1_800_000_000,
        )


def test_journal_rejects_dangling_journal_file_symlink(tmp_path: Path) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.root.mkdir(mode=0o700)
    journal.journal_path.symlink_to(tmp_path / "missing-target")

    with pytest.raises(ErasureJournalError, match="file is invalid"):
        journal.read_all()
    with pytest.raises(ErasureJournalError, match="file is invalid"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-1"],
            now=1_800_000_000,
        )
