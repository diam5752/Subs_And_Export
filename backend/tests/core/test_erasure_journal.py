from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.core import erasure_journal as journal_module
from backend.app.core.erasure_journal import (
    ErasureJournal,
    ErasureJournalError,
    ErasureTombstone,
    JobTerminalErasureTombstone,
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
    assert stat.S_IMODE(journal.checkpoint_path.stat().st_mode) == 0o600


def test_journal_requires_matching_live_volume_continuity(tmp_path: Path) -> None:
    continuity_id = "a" * 64
    root = tmp_path / "journal"
    anchor_path = tmp_path / "host-state" / "erasure-journal-anchor.json"
    journal = ErasureJournal(
        root,
        retention_days=30,
        expected_continuity_id=continuity_id,
        anchor_path=anchor_path,
    )

    with pytest.raises(ErasureJournalError, match="continuity is unavailable"):
        journal.read_all()

    root.mkdir(exist_ok=True)
    journal.continuity_path.write_text(f"{continuity_id}\n", encoding="ascii")
    # REGRESSION: a matching static marker must never make a missing ledger
    # look like an authoritative empty erasure history.
    with pytest.raises(ErasureJournalError, match="has not been initialized"):
        journal.read_all()

    journal.initialize()
    assert journal.read_all() == []

    journal.continuity_path.write_text(f"{'b' * 64}\n", encoding="ascii")
    with pytest.raises(ErasureJournalError, match="does not match this host"):
        journal.read_all()


def test_journal_detects_missing_truncated_and_rolled_back_state(tmp_path: Path) -> None:
    continuity_id = "d" * 64
    root = tmp_path / "journal"
    root.mkdir()
    (root / ".continuity-id").write_text(f"{continuity_id}\n", encoding="ascii")
    anchor_path = tmp_path / "host-state" / "erasure-journal-anchor.json"
    journal = ErasureJournal(
        root,
        retention_days=30,
        expected_continuity_id=continuity_id,
        anchor_path=anchor_path,
    )
    journal.initialize()
    first = journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-1"],
        now=1_800_000_000,
    )
    first_ledger = journal.journal_path.read_bytes()
    first_checkpoint = journal.checkpoint_path.read_bytes()
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-2"],
        now=1_800_000_001,
    )
    current_ledger = journal.journal_path.read_bytes()
    current_checkpoint = journal.checkpoint_path.read_bytes()
    current_anchor = anchor_path.read_bytes()

    # REGRESSION: a valid earlier ledger prefix is still a rollback, not a
    # valid journal, once a newer generation has been acknowledged.
    journal.journal_path.write_bytes(first_ledger)
    with pytest.raises(ErasureJournalError, match="ledger does not match its checkpoint"):
        journal.read_all()

    journal.journal_path.write_bytes(first_ledger)
    journal.checkpoint_path.write_bytes(first_checkpoint)
    with pytest.raises(ErasureJournalError, match="older than the external anchor"):
        journal.read_all()

    journal.journal_path.write_bytes(current_ledger)
    journal.checkpoint_path.write_bytes(current_checkpoint)
    anchor_path.write_bytes(current_anchor)
    assert journal.read_all()[0] == first

    journal.journal_path.unlink()
    with pytest.raises(ErasureJournalError, match="ledger is unavailable"):
        journal.read_all()


def test_journal_append_does_not_reparse_retained_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-1"],
        now=1_800_000_000,
    )

    def reject_full_scan() -> object:
        raise AssertionError("append reparsed retained history")

    # REGRESSION: append used to decode every previous JSONL record while
    # holding the global journal lock, producing triangular O(n^2) work.
    monkeypatch.setattr(journal, "_scan_journal_unlocked", reject_full_scan)
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-2"],
        now=1_800_000_001,
    )


def test_journal_recovers_fsynced_append_from_pending_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    first = journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-1"],
        now=1_800_000_000,
    )
    write_checkpoint = journal._write_checkpoint_unlocked

    def interrupt_after_ledger_fsync(_checkpoint: object) -> None:
        raise ErasureJournalError("simulated checkpoint interruption")

    monkeypatch.setattr(journal, "_write_checkpoint_unlocked", interrupt_after_ledger_fsync)
    with pytest.raises(ErasureJournalError, match="simulated checkpoint interruption"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-2"],
            now=1_800_000_001,
        )

    monkeypatch.setattr(journal, "_write_checkpoint_unlocked", write_checkpoint)
    recovered = journal.read_all()
    assert recovered[0] == first
    assert len(recovered) == 2
    for entry, expected_job_ids in zip(
        recovered,
        [["job-1"], ["job-2"]],
        strict=True,
    ):
        assert isinstance(entry, ErasureTombstone)
        assert entry.job_ids == expected_job_ids
    assert not journal.pending_path.exists()


def test_journal_recovers_checkpoint_before_external_anchor_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    continuity_id = "e" * 64
    root = tmp_path / "journal"
    root.mkdir()
    (root / ".continuity-id").write_text(f"{continuity_id}\n", encoding="ascii")
    anchor_path = tmp_path / "host-state" / "erasure-journal-anchor.json"
    journal = ErasureJournal(
        root,
        retention_days=30,
        expected_continuity_id=continuity_id,
        anchor_path=anchor_path,
    )
    journal.initialize()
    write_anchor = journal._write_anchor_unlocked

    def interrupt_before_anchor(_checkpoint: object) -> None:
        raise ErasureJournalError("simulated anchor interruption")

    monkeypatch.setattr(journal, "_write_anchor_unlocked", interrupt_before_anchor)
    with pytest.raises(ErasureJournalError, match="simulated anchor interruption"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-1"],
            now=1_800_000_000,
        )

    monkeypatch.setattr(journal, "_write_anchor_unlocked", write_anchor)
    recovered = journal.read_all()
    assert len(recovered) == 1
    assert isinstance(recovered[0], ErasureTombstone)
    assert recovered[0].job_ids == ["job-1"]
    assert journal.checkpoint_path.read_bytes() == anchor_path.read_bytes()
    assert not journal.pending_path.exists()


def test_append_rejects_tampered_tail_without_full_history_scan(tmp_path: Path) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-1"],
        now=1_800_000_000,
    )
    tampered = journal.journal_path.read_bytes().replace(b'"job-1"', b'"job-2"')
    journal.journal_path.write_bytes(tampered)

    with pytest.raises(ErasureJournalError, match="ledger does not match its checkpoint"):
        journal.append(
            kind="job",
            user_id="user-1",
            job_ids=["job-3"],
            now=1_800_000_001,
        )


def test_full_read_detects_same_size_historical_tampering(tmp_path: Path) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-1"],
        now=1_800_000_000,
    )
    journal.append(
        kind="job",
        user_id="user-1",
        job_ids=["job-2"],
        now=1_800_000_001,
    )
    tampered = journal.journal_path.read_bytes().replace(b'"user-1"', b'"user-2"', 1)
    journal.journal_path.write_bytes(tampered)

    with pytest.raises(ErasureJournalError, match="ledger does not match its checkpoint"):
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


def test_job_terminal_tombstone_roundtrips_canonical_restore_intent(
    tmp_path: Path,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)

    appended = journal.append_job_terminal(
        user_id="user-1",
        job_ids=["job-b", "job-a", "job-a"],
        terminal_status="cancelled",
        now=1_800_000_000,
    )

    assert isinstance(appended, JobTerminalErasureTombstone)
    assert appended.job_ids == ["job-a", "job-b"]
    assert journal.read_all() == [appended]
    raw = json.loads(journal.journal_path.read_text(encoding="utf-8"))
    assert set(raw) == {
        "schema_version",
        "event_id",
        "kind",
        "created_at",
        "user_id",
        "job_ids",
        "terminal_status",
    }
    assert raw["kind"] == "job_terminal"
    assert raw["terminal_status"] == "cancelled"


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"terminal_status": "completed"}, "terminal job event"),
        ({"job_ids": []}, "terminal job identifiers"),
        ({"job_ids": ["job-b", "job-a"]}, "not canonical"),
    ],
)
def test_job_terminal_decode_rejects_invalid_restore_intent(
    mutation: dict[str, object],
    error: str,
) -> None:
    raw: dict[str, object] = {
        "schema_version": 1,
        "event_id": "a" * 32,
        "kind": "job_terminal",
        "created_at": 1_800_000_000,
        "user_id": "user-1",
        "job_ids": ["job-a"],
        "terminal_status": "cancelled",
    }
    raw.update(mutation)

    with pytest.raises(ErasureJournalError, match=error):
        ErasureJournal._decode(
            json.dumps(raw, separators=(",", ":"), sort_keys=True).encode() + b"\n",
        )


def test_job_terminal_decode_rejects_incomplete_schema() -> None:
    raw = {
        "schema_version": 1,
        "event_id": "a" * 32,
        "kind": "job_terminal",
        "created_at": 1_800_000_000,
        "user_id": "user-1",
        "job_ids": ["job-a"],
    }

    with pytest.raises(ErasureJournalError, match="invalid record schema"):
        ErasureJournal._decode(json.dumps(raw).encode() + b"\n")


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
    journal.initialize()

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


def test_configured_production_journal_requires_isolated_external_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = {
        "is_dev": False,
        "data_dir": tmp_path / "media",
        "erasure_journal_dir": tmp_path / "journal",
        "erasure_journal_retention_days": 30,
        "erasure_journal_continuity_id": "a" * 64,
    }
    monkeypatch.setattr(
        journal_module,
        "settings",
        SimpleNamespace(**common, erasure_journal_anchor_path=None),
    )

    with pytest.raises(ErasureJournalError, match="external anchor path is required"):
        journal_module.configured_erasure_journal()

    monkeypatch.setattr(
        journal_module,
        "settings",
        SimpleNamespace(
            **common,
            erasure_journal_anchor_path=tmp_path / "journal" / "anchor.json",
        ),
    )
    with pytest.raises(ErasureJournalError, match="must be isolated"):
        journal_module.configured_erasure_journal()


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
