"""Durable privacy tombstones that survive database and media restores."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Literal

from .config import settings

TombstoneKind = Literal["workspace", "job", "account"]
_ALLOWED_KINDS = frozenset({"workspace", "job", "account"})
ProviderTombstoneKind = Literal["provider_transcript"]
ProviderName = Literal["elevenlabs"]
OrphanTombstoneKind = Literal["orphan_workspace"]
JobTerminalTombstoneKind = Literal["job_terminal"]
JobTerminalStatus = Literal["cancelled", "failed"]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}$")
_JOURNAL_FILENAME = "tombstones.jsonl"
_LOCK_FILENAME = ".journal.lock"
_CONTINUITY_FILENAME = ".continuity-id"
_CHECKPOINT_FILENAME = ".journal-checkpoint.json"
_PENDING_FILENAME = ".journal-pending.json"
_CONTINUITY_ID = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_STATE_SCHEMA_VERSION = 1
_STATE_DOMAIN = b"gsubs-erasure-journal-state/v1"
_MAX_STATE_BYTES = 16 * 1024
MAX_TOMBSTONE_BYTES = 8 * 1024 * 1024
MAX_JOURNAL_BYTES = 512 * 1024 * 1024


class ErasureJournalError(RuntimeError):
    """Raised when a privacy tombstone cannot be durably stored or trusted."""


@dataclass(frozen=True, slots=True)
class ErasureTombstone:
    schema_version: int
    event_id: str
    kind: TombstoneKind
    created_at: int
    user_id: str
    job_ids: list[str]


@dataclass(frozen=True, slots=True)
class ProviderTranscriptErasureTombstone:
    """Provider erasure intent without account, filename, or transcript data."""

    schema_version: int
    event_id: str
    kind: ProviderTombstoneKind
    created_at: int
    provider: ProviderName
    transcript_id: str


@dataclass(frozen=True, slots=True)
class OrphanWorkspaceErasureTombstone:
    """Filesystem erasure intent for a workspace with no surviving owner row."""

    schema_version: int
    event_id: str
    kind: OrphanTombstoneKind
    created_at: int
    job_ids: list[str]


@dataclass(frozen=True, slots=True)
class JobTerminalErasureTombstone:
    """Restore-safe intent to clean media and finish a processing job."""

    schema_version: int
    event_id: str
    kind: JobTerminalTombstoneKind
    created_at: int
    user_id: str
    job_ids: list[str]
    terminal_status: JobTerminalStatus


ErasureJournalEntry = (
    ErasureTombstone
    | ProviderTranscriptErasureTombstone
    | OrphanWorkspaceErasureTombstone
    | JobTerminalErasureTombstone
)


@dataclass(frozen=True, slots=True)
class JournalCheckpoint:
    """Integrity state for one acknowledged journal generation."""

    schema_version: int
    continuity_id: str
    generation: int
    entry_count: int
    journal_size: int
    chain_digest: str
    tail_size: int
    tail_digest: str


@dataclass(frozen=True, slots=True)
class PendingJournalMutation:
    """Crash-recovery record written before a journal mutation."""

    schema_version: int
    operation: Literal["append", "replace"]
    before: JournalCheckpoint
    after: JournalCheckpoint


class ErasureJournal:
    """Append-only, fsync-backed erasure intent journal."""

    def __init__(
        self,
        root: Path,
        *,
        retention_days: int,
        expected_continuity_id: str | None = None,
        anchor_path: Path | None = None,
    ) -> None:
        if retention_days < 14 or retention_days > 365:
            raise ValueError("Erasure journal retention must be between 14 and 365 days")
        if expected_continuity_id is not None and _CONTINUITY_ID.fullmatch(
            expected_continuity_id,
        ) is None:
            raise ValueError("Erasure journal continuity identifier is invalid")
        self.root = root
        self.retention_days = retention_days
        self.expected_continuity_id = expected_continuity_id
        self.anchor_path = anchor_path
        self.journal_path = root / _JOURNAL_FILENAME
        self.lock_path = root / _LOCK_FILENAME
        self.continuity_path = root / _CONTINUITY_FILENAME
        self.checkpoint_path = root / _CHECKPOINT_FILENAME
        self.pending_path = root / _PENDING_FILENAME

    def append(
        self,
        *,
        kind: TombstoneKind,
        user_id: str,
        job_ids: list[str],
        now: int | None = None,
    ) -> ErasureTombstone:
        """Persist an authoritative erasure intent before destructive work."""
        created_at = int(time.time()) if now is None else now
        tombstone = ErasureTombstone(
            schema_version=1,
            event_id=uuid.uuid4().hex,
            kind=kind,
            created_at=created_at,
            user_id=user_id,
            job_ids=sorted(set(job_ids)),
        )
        self._append_entry(tombstone)
        return tombstone

    def append_provider_transcript(
        self,
        *,
        provider: ProviderName,
        transcript_id: str,
        now: int | None = None,
    ) -> ProviderTranscriptErasureTombstone:
        """Persist an opaque provider deletion intent before the first DELETE."""
        created_at = int(time.time()) if now is None else now
        tombstone = ProviderTranscriptErasureTombstone(
            schema_version=1,
            event_id=uuid.uuid4().hex,
            kind="provider_transcript",
            created_at=created_at,
            provider=provider,
            transcript_id=transcript_id,
        )
        self._append_entry(tombstone)
        return tombstone

    def append_orphan_workspace(
        self,
        *,
        job_ids: list[str],
        now: int | None = None,
    ) -> OrphanWorkspaceErasureTombstone:
        """Persist exact unowned workspace IDs before retention removes them."""
        created_at = int(time.time()) if now is None else now
        tombstone = OrphanWorkspaceErasureTombstone(
            schema_version=1,
            event_id=uuid.uuid4().hex,
            kind="orphan_workspace",
            created_at=created_at,
            job_ids=sorted(set(job_ids)),
        )
        self._append_entry(tombstone)
        return tombstone

    def append_job_terminal(
        self,
        *,
        user_id: str,
        job_ids: list[str],
        terminal_status: JobTerminalStatus,
        now: int | None = None,
    ) -> JobTerminalErasureTombstone:
        """Persist cleanup plus terminal job state before removing media."""
        created_at = int(time.time()) if now is None else now
        tombstone = JobTerminalErasureTombstone(
            schema_version=1,
            event_id=uuid.uuid4().hex,
            kind="job_terminal",
            created_at=created_at,
            user_id=user_id,
            job_ids=sorted(set(job_ids)),
            terminal_status=terminal_status,
        )
        self._append_entry(tombstone)
        return tombstone

    def _append_entry(self, tombstone: ErasureJournalEntry) -> None:
        self._validate(tombstone)
        encoded = self._encode(tombstone)
        with self._exclusive_lock() as continuity_id:
            _entries, checkpoint = self._load_current_checkpoint_unlocked(
                continuity_id=continuity_id,
                full_validation=False,
            )
            if checkpoint.journal_size + len(encoded) > MAX_JOURNAL_BYTES:
                raise ErasureJournalError("Erasure journal exceeds its safe size limit")
            next_checkpoint = JournalCheckpoint(
                schema_version=_STATE_SCHEMA_VERSION,
                continuity_id=continuity_id,
                generation=checkpoint.generation + 1,
                entry_count=checkpoint.entry_count + 1,
                journal_size=checkpoint.journal_size + len(encoded),
                chain_digest=self._advance_chain(checkpoint.chain_digest, encoded),
                tail_size=len(encoded),
                tail_digest=self._digest(encoded),
            )
            pending = PendingJournalMutation(
                schema_version=_STATE_SCHEMA_VERSION,
                operation="append",
                before=checkpoint,
                after=next_checkpoint,
            )
            try:
                self._write_pending_unlocked(pending)
                with self.journal_path.open("ab") as journal:
                    os.chmod(self.journal_path, 0o600)
                    journal.write(encoded)
                    journal.flush()
                    os.fsync(journal.fileno())
                self._write_checkpoint_unlocked(next_checkpoint)
                self._write_anchor_unlocked(next_checkpoint)
                self._clear_pending_unlocked()
            except ErasureJournalError:
                raise
            except OSError as exc:
                raise ErasureJournalError("Erasure intent could not be stored durably") from exc

    def initialize(self) -> None:
        """Explicitly initialize an empty production ledger and both anchors.

        Production callers must gate this method with independent first-use
        evidence. Normal reads never interpret a matching continuity marker as
        permission to recreate missing state.
        """
        with self._exclusive_lock(initialize=True) as continuity_id:
            self._initialize_unlocked(continuity_id=continuity_id, explicit=True)
            self._load_current_checkpoint_unlocked(
                continuity_id=continuity_id,
                full_validation=True,
            )

    def read_all(self) -> list[ErasureJournalEntry]:
        """Read and strictly validate every retained tombstone."""
        with self._exclusive_lock() as continuity_id:
            entries, _checkpoint = self._load_current_checkpoint_unlocked(
                continuity_id=continuity_id,
                full_validation=True,
            )
            return entries

    def prune_expired(self, *, now: int | None = None) -> int:
        """Prune only entries older than the configured backup-safe window."""
        current_time = int(time.time()) if now is None else now
        if type(current_time) is not int or current_time <= 0:
            raise ValueError("Erasure journal cutoff must be a positive integer")
        cutoff = current_time - (self.retention_days * 86_400)
        with self._exclusive_lock() as continuity_id:
            entries, checkpoint = self._load_current_checkpoint_unlocked(
                continuity_id=continuity_id,
                full_validation=True,
            )
            retained = [entry for entry in entries if entry.created_at >= cutoff]
            removed = len(entries) - len(retained)
            if removed:
                self._replace_unlocked(
                    retained,
                    before=checkpoint,
                    continuity_id=continuity_id,
                )
            return removed

    @contextmanager
    def _exclusive_lock(self, *, initialize: bool = False) -> Iterator[str]:
        self._ensure_root()
        try:
            if self.lock_path.is_symlink():
                raise ErasureJournalError("Erasure journal lock file is invalid")
            with self.lock_path.open("a+b") as lock_file:
                os.chmod(self.lock_path, 0o600)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    continuity_id = self._verify_continuity_unlocked(
                        allow_local_creation=self.expected_continuity_id is None,
                    )
                    if not initialize:
                        self._initialize_unlocked(
                            continuity_id=continuity_id,
                            explicit=False,
                        )
                    yield continuity_id
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal lock is unavailable") from exc

    def _ensure_root(self) -> None:
        try:
            if self.root.is_symlink():
                raise ErasureJournalError("Erasure journal directory cannot be a symlink")
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not self.root.is_dir() or self.root.is_symlink():
                raise ErasureJournalError("Erasure journal directory is invalid")
            os.chmod(self.root, 0o700)
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal directory is unavailable") from exc

    def _verify_continuity_unlocked(self, *, allow_local_creation: bool) -> str:
        """Reject a missing or replaced production journal volume."""
        expected = self.expected_continuity_id
        if expected is None and allow_local_creation and not self.continuity_path.exists():
            if self.continuity_path.is_symlink():
                raise ErasureJournalError("Erasure journal continuity is unavailable")
            expected = uuid.uuid4().hex + uuid.uuid4().hex
            self._write_private_bytes_atomic(
                self.continuity_path,
                f"{expected}\n".encode("ascii"),
            )
        try:
            if self.continuity_path.is_symlink() or not self.continuity_path.is_file():
                raise ErasureJournalError("Erasure journal continuity is unavailable")
            raw = self.continuity_path.read_bytes()
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal continuity could not be read") from exc
        normalized = raw.removesuffix(b"\n")
        try:
            actual = normalized.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ErasureJournalError("Erasure journal continuity is invalid") from exc
        if _CONTINUITY_ID.fullmatch(actual) is None:
            raise ErasureJournalError("Erasure journal continuity is invalid")
        if expected is not None and actual != expected:
            raise ErasureJournalError("Erasure journal continuity does not match this host")
        return actual

    def _initialize_unlocked(self, *, continuity_id: str, explicit: bool) -> None:
        self._reject_invalid_state_paths_unlocked()
        journal_exists = self.journal_path.exists()
        checkpoint_exists = self.checkpoint_path.exists()
        anchor_exists = self.anchor_path is None or self.anchor_path.exists()
        pending_exists = self.pending_path.exists()

        if journal_exists and checkpoint_exists and anchor_exists:
            return
        if pending_exists:
            raise ErasureJournalError("Erasure journal has an incomplete initialization")

        state_exists = journal_exists or checkpoint_exists or (
            self.anchor_path is not None and anchor_exists
        )
        if explicit:
            if state_exists:
                raise ErasureJournalError("Erasure journal is only partially initialized")
            self._create_empty_state_unlocked(continuity_id)
            return

        if self.expected_continuity_id is not None:
            if checkpoint_exists and anchor_exists and not journal_exists:
                raise ErasureJournalError("Erasure journal ledger is unavailable")
            if journal_exists and anchor_exists and not checkpoint_exists:
                raise ErasureJournalError("Erasure journal checkpoint is unavailable")
            if journal_exists and checkpoint_exists and not anchor_exists:
                raise ErasureJournalError("Erasure journal external anchor is unavailable")
            raise ErasureJournalError("Erasure journal has not been initialized")

        if journal_exists and not checkpoint_exists and self.anchor_path is None:
            # One-time development migration. Production never reaches this
            # path because configured continuity requires explicit bootstrap.
            entries, checkpoint = self._scan_journal_unlocked(
                continuity_id=continuity_id,
                generation=0,
            )
            del entries
            self._write_checkpoint_unlocked(checkpoint)
            return
        if state_exists:
            raise ErasureJournalError("Erasure journal is only partially initialized")
        self._create_empty_state_unlocked(continuity_id)

    def _create_empty_state_unlocked(self, continuity_id: str) -> None:
        try:
            with self.journal_path.open("xb") as journal:
                os.chmod(self.journal_path, 0o600)
                journal.flush()
                os.fsync(journal.fileno())
            self._fsync_directory(self.root)
            checkpoint = self._empty_checkpoint(continuity_id)
            self._write_checkpoint_unlocked(checkpoint)
            self._write_anchor_unlocked(checkpoint)
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal could not be initialized durably") from exc

    def _reject_invalid_state_paths_unlocked(self) -> None:
        for path, message in (
            (self.journal_path, "Erasure journal file is invalid"),
            (self.checkpoint_path, "Erasure journal checkpoint is invalid"),
            (self.pending_path, "Erasure journal pending state is invalid"),
        ):
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ErasureJournalError(message)
        if self.anchor_path is not None and (
            self.anchor_path.is_symlink()
            or (self.anchor_path.exists() and not self.anchor_path.is_file())
        ):
            raise ErasureJournalError("Erasure journal external anchor is invalid")

    def _load_current_checkpoint_unlocked(
        self,
        *,
        continuity_id: str,
        full_validation: bool,
    ) -> tuple[list[ErasureJournalEntry], JournalCheckpoint]:
        self._recover_pending_unlocked(continuity_id)
        checkpoint = self._read_checkpoint_unlocked(
            self.checkpoint_path,
            label="checkpoint",
        )
        self._verify_checkpoint_continuity(checkpoint, continuity_id)
        self._verify_external_anchor_unlocked(checkpoint, continuity_id)
        if full_validation:
            entries, observed = self._scan_journal_unlocked(
                continuity_id=continuity_id,
                generation=checkpoint.generation,
            )
            if not self._same_checkpoint(checkpoint, observed):
                raise ErasureJournalError("Erasure journal ledger does not match its checkpoint")
        else:
            entries = []
            self._verify_tail_unlocked(checkpoint)
        return entries, checkpoint

    def _verify_external_anchor_unlocked(
        self,
        checkpoint: JournalCheckpoint,
        continuity_id: str,
    ) -> None:
        if self.anchor_path is None:
            return
        if not self.anchor_path.exists():
            raise ErasureJournalError("Erasure journal external anchor is unavailable")
        anchor = self._read_checkpoint_unlocked(
            self.anchor_path,
            label="external anchor",
        )
        self._verify_checkpoint_continuity(anchor, continuity_id)
        if checkpoint.generation < anchor.generation:
            raise ErasureJournalError("Erasure journal checkpoint is older than the external anchor")
        if checkpoint.generation > anchor.generation:
            raise ErasureJournalError("Erasure journal external anchor is older than the checkpoint")
        if not self._same_checkpoint(checkpoint, anchor):
            raise ErasureJournalError("Erasure journal external anchor does not match the checkpoint")

    def _verify_tail_unlocked(self, checkpoint: JournalCheckpoint) -> None:
        if self.journal_path.is_symlink():
            raise ErasureJournalError("Erasure journal file is invalid")
        if not self.journal_path.exists():
            raise ErasureJournalError("Erasure journal ledger is unavailable")
        if not self.journal_path.is_file():
            raise ErasureJournalError("Erasure journal file is invalid")
        try:
            actual_size = self.journal_path.stat().st_size
            if actual_size > MAX_JOURNAL_BYTES:
                raise ErasureJournalError("Erasure journal exceeds its safe size limit")
            if actual_size != checkpoint.journal_size:
                raise ErasureJournalError("Erasure journal ledger does not match its checkpoint")
            if checkpoint.tail_size > actual_size:
                raise ErasureJournalError("Erasure journal checkpoint tail is invalid")
            if checkpoint.tail_size == 0:
                if actual_size != 0 or checkpoint.entry_count != 0:
                    raise ErasureJournalError("Erasure journal checkpoint tail is invalid")
                return
            with self.journal_path.open("rb") as journal:
                journal.seek(-checkpoint.tail_size, os.SEEK_END)
                tail = journal.read(checkpoint.tail_size)
            if (
                len(tail) != checkpoint.tail_size
                or not tail.endswith(b"\n")
                or self._digest(tail) != checkpoint.tail_digest
            ):
                raise ErasureJournalError("Erasure journal ledger does not match its checkpoint")
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal could not be read") from exc

    def _scan_journal_unlocked(
        self,
        *,
        continuity_id: str,
        generation: int,
    ) -> tuple[list[ErasureJournalEntry], JournalCheckpoint]:
        if self.journal_path.is_symlink():
            raise ErasureJournalError("Erasure journal file is invalid")
        if not self.journal_path.exists():
            raise ErasureJournalError("Erasure journal ledger is unavailable")
        if not self.journal_path.is_file():
            raise ErasureJournalError("Erasure journal file is invalid")
        try:
            if self.journal_path.stat().st_size > MAX_JOURNAL_BYTES:
                raise ErasureJournalError("Erasure journal exceeds its safe size limit")
            entries: list[ErasureJournalEntry] = []
            event_ids: set[str] = set()
            chain_digest = self._genesis_digest(continuity_id)
            journal_size = 0
            tail = b""
            with self.journal_path.open("rb") as journal:
                while line := journal.readline(MAX_TOMBSTONE_BYTES + 1):
                    if len(line) > MAX_TOMBSTONE_BYTES:
                        raise ErasureJournalError("Erasure journal contains an oversized record")
                    if not line.endswith(b"\n"):
                        raise ErasureJournalError("Erasure journal contains an incomplete record")
                    entry = self._decode(line)
                    if entry.event_id in event_ids:
                        raise ErasureJournalError("Erasure journal contains a duplicate event")
                    event_ids.add(entry.event_id)
                    entries.append(entry)
                    chain_digest = self._advance_chain(chain_digest, line)
                    journal_size += len(line)
                    tail = line
            checkpoint = JournalCheckpoint(
                schema_version=_STATE_SCHEMA_VERSION,
                continuity_id=continuity_id,
                generation=generation,
                entry_count=len(entries),
                journal_size=journal_size,
                chain_digest=chain_digest,
                tail_size=len(tail),
                tail_digest=self._digest(tail),
            )
            return entries, checkpoint
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal could not be read") from exc

    def _replace_unlocked(
        self,
        entries: list[ErasureJournalEntry],
        *,
        before: JournalCheckpoint,
        continuity_id: str,
    ) -> None:
        temporary_path = self.root / f".{_JOURNAL_FILENAME}.{uuid.uuid4().hex}.tmp"
        chain_digest = self._genesis_digest(continuity_id)
        journal_size = 0
        tail = b""
        for entry in entries:
            encoded = self._encode(entry)
            chain_digest = self._advance_chain(chain_digest, encoded)
            journal_size += len(encoded)
            tail = encoded
        after = JournalCheckpoint(
            schema_version=_STATE_SCHEMA_VERSION,
            continuity_id=continuity_id,
            generation=before.generation + 1,
            entry_count=len(entries),
            journal_size=journal_size,
            chain_digest=chain_digest,
            tail_size=len(tail),
            tail_digest=self._digest(tail),
        )
        pending = PendingJournalMutation(
            schema_version=_STATE_SCHEMA_VERSION,
            operation="replace",
            before=before,
            after=after,
        )
        try:
            self._write_pending_unlocked(pending)
            with temporary_path.open("xb") as temporary:
                os.chmod(temporary_path, 0o600)
                for entry in entries:
                    temporary.write(self._encode(entry))
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(self.journal_path)
            os.chmod(self.journal_path, 0o600)
            self._fsync_directory(self.root)
            self._write_checkpoint_unlocked(after)
            self._write_anchor_unlocked(after)
            self._clear_pending_unlocked()
        except ErasureJournalError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise ErasureJournalError("Erasure journal could not be pruned durably") from exc

    def _recover_pending_unlocked(self, continuity_id: str) -> None:
        if not self.pending_path.exists():
            return
        pending = self._read_pending_unlocked()
        self._verify_checkpoint_continuity(pending.before, continuity_id)
        self._verify_checkpoint_continuity(pending.after, continuity_id)
        if pending.after.generation != pending.before.generation + 1:
            raise ErasureJournalError("Erasure journal pending generation is invalid")
        existing_checkpoint = self._read_checkpoint_unlocked(
            self.checkpoint_path,
            label="checkpoint",
        )
        allowed_checkpoints = (pending.before, pending.after)
        if not any(
            self._same_checkpoint(existing_checkpoint, allowed)
            for allowed in allowed_checkpoints
        ):
            raise ErasureJournalError("Erasure journal checkpoint conflicts with pending state")
        if self.anchor_path is not None:
            existing_anchor = self._read_checkpoint_unlocked(
                self.anchor_path,
                label="external anchor",
            )
            if not any(
                self._same_checkpoint(existing_anchor, allowed)
                for allowed in allowed_checkpoints
            ):
                raise ErasureJournalError("Erasure journal external anchor conflicts with pending state")

        _entries, observed_before = self._scan_journal_unlocked(
            continuity_id=continuity_id,
            generation=pending.before.generation,
        )
        if self._same_physical_state(observed_before, pending.before):
            if not self._same_checkpoint(existing_checkpoint, pending.before):
                raise ErasureJournalError("Erasure journal pending state would roll back its checkpoint")
            if self.anchor_path is not None and not self._same_checkpoint(
                existing_anchor,
                pending.before,
            ):
                raise ErasureJournalError("Erasure journal pending state would roll back its external anchor")
            self._clear_pending_unlocked()
            return

        observed_after = JournalCheckpoint(
            schema_version=observed_before.schema_version,
            continuity_id=observed_before.continuity_id,
            generation=pending.after.generation,
            entry_count=observed_before.entry_count,
            journal_size=observed_before.journal_size,
            chain_digest=observed_before.chain_digest,
            tail_size=observed_before.tail_size,
            tail_digest=observed_before.tail_digest,
        )
        if not self._same_checkpoint(observed_after, pending.after):
            raise ErasureJournalError("Erasure journal ledger conflicts with pending state")
        self._write_checkpoint_unlocked(pending.after)
        self._write_anchor_unlocked(pending.after)
        self._clear_pending_unlocked()

    def _read_checkpoint_unlocked(self, path: Path, *, label: str) -> JournalCheckpoint:
        try:
            if path.is_symlink() or not path.is_file():
                raise ErasureJournalError(f"Erasure journal {label} is unavailable")
            raw_bytes = path.read_bytes()
            if len(raw_bytes) > _MAX_STATE_BYTES:
                raise ErasureJournalError(f"Erasure journal {label} is invalid")
            raw = json.loads(raw_bytes)
        except ErasureJournalError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErasureJournalError(f"Erasure journal {label} could not be read") from exc
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "continuity_id",
            "generation",
            "entry_count",
            "journal_size",
            "chain_digest",
            "tail_size",
            "tail_digest",
        }:
            raise ErasureJournalError(f"Erasure journal {label} is invalid")
        checkpoint = JournalCheckpoint(
            schema_version=raw["schema_version"],
            continuity_id=raw["continuity_id"],
            generation=raw["generation"],
            entry_count=raw["entry_count"],
            journal_size=raw["journal_size"],
            chain_digest=raw["chain_digest"],
            tail_size=raw["tail_size"],
            tail_digest=raw["tail_digest"],
        )
        self._validate_checkpoint(checkpoint, label=label)
        return checkpoint

    def _read_pending_unlocked(self) -> PendingJournalMutation:
        try:
            if self.pending_path.is_symlink() or not self.pending_path.is_file():
                raise ErasureJournalError("Erasure journal pending state is invalid")
            raw_bytes = self.pending_path.read_bytes()
            if len(raw_bytes) > _MAX_STATE_BYTES:
                raise ErasureJournalError("Erasure journal pending state is invalid")
            raw = json.loads(raw_bytes)
        except ErasureJournalError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErasureJournalError("Erasure journal pending state could not be read") from exc
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "operation",
            "before",
            "after",
        }:
            raise ErasureJournalError("Erasure journal pending state is invalid")
        before = self._checkpoint_from_mapping(raw["before"], label="pending state")
        after = self._checkpoint_from_mapping(raw["after"], label="pending state")
        pending = PendingJournalMutation(
            schema_version=raw["schema_version"],
            operation=raw["operation"],
            before=before,
            after=after,
        )
        if (
            pending.schema_version != _STATE_SCHEMA_VERSION
            or pending.operation not in {"append", "replace"}
        ):
            raise ErasureJournalError("Erasure journal pending state is invalid")
        return pending

    def _checkpoint_from_mapping(self, raw: object, *, label: str) -> JournalCheckpoint:
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "continuity_id",
            "generation",
            "entry_count",
            "journal_size",
            "chain_digest",
            "tail_size",
            "tail_digest",
        }:
            raise ErasureJournalError(f"Erasure journal {label} is invalid")
        checkpoint = JournalCheckpoint(
            schema_version=raw["schema_version"],
            continuity_id=raw["continuity_id"],
            generation=raw["generation"],
            entry_count=raw["entry_count"],
            journal_size=raw["journal_size"],
            chain_digest=raw["chain_digest"],
            tail_size=raw["tail_size"],
            tail_digest=raw["tail_digest"],
        )
        self._validate_checkpoint(checkpoint, label=label)
        return checkpoint

    @staticmethod
    def _validate_checkpoint(checkpoint: JournalCheckpoint, *, label: str) -> None:
        if (
            checkpoint.schema_version != _STATE_SCHEMA_VERSION
            or not isinstance(checkpoint.continuity_id, str)
            or _CONTINUITY_ID.fullmatch(checkpoint.continuity_id) is None
            or type(checkpoint.generation) is not int
            or checkpoint.generation < 0
            or type(checkpoint.entry_count) is not int
            or checkpoint.entry_count < 0
            or type(checkpoint.journal_size) is not int
            or checkpoint.journal_size < 0
            or checkpoint.journal_size > MAX_JOURNAL_BYTES
            or not isinstance(checkpoint.chain_digest, str)
            or _DIGEST.fullmatch(checkpoint.chain_digest) is None
            or type(checkpoint.tail_size) is not int
            or checkpoint.tail_size < 0
            or checkpoint.tail_size > MAX_TOMBSTONE_BYTES
            or not isinstance(checkpoint.tail_digest, str)
            or _DIGEST.fullmatch(checkpoint.tail_digest) is None
            or (checkpoint.entry_count == 0) != (checkpoint.journal_size == 0)
            or (checkpoint.entry_count == 0) != (checkpoint.tail_size == 0)
        ):
            raise ErasureJournalError(f"Erasure journal {label} is invalid")

    @staticmethod
    def _verify_checkpoint_continuity(
        checkpoint: JournalCheckpoint,
        continuity_id: str,
    ) -> None:
        if checkpoint.continuity_id != continuity_id:
            raise ErasureJournalError("Erasure journal state has the wrong continuity binding")

    def _write_checkpoint_unlocked(self, checkpoint: JournalCheckpoint) -> None:
        self._write_private_bytes_atomic(
            self.checkpoint_path,
            self._encode_checkpoint(checkpoint),
        )

    def _write_anchor_unlocked(self, checkpoint: JournalCheckpoint) -> None:
        if self.anchor_path is None:
            return
        self._write_private_bytes_atomic(
            self.anchor_path,
            self._encode_checkpoint(checkpoint),
        )

    def _write_pending_unlocked(self, pending: PendingJournalMutation) -> None:
        encoded = (
            json.dumps(
                {
                    "schema_version": pending.schema_version,
                    "operation": pending.operation,
                    "before": asdict(pending.before),
                    "after": asdict(pending.after),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            + b"\n"
        )
        self._write_private_bytes_atomic(self.pending_path, encoded)

    def _clear_pending_unlocked(self) -> None:
        try:
            self.pending_path.unlink(missing_ok=True)
            self._fsync_directory(self.root)
        except OSError as exc:
            raise ErasureJournalError("Erasure journal pending state could not be cleared") from exc

    @staticmethod
    def _encode_checkpoint(checkpoint: JournalCheckpoint) -> bytes:
        return (
            json.dumps(
                asdict(checkpoint),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            + b"\n"
        )

    def _write_private_bytes_atomic(self, path: Path, content: bytes) -> None:
        parent = path.parent
        temporary_path = parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            if parent.is_symlink():
                raise ErasureJournalError("Erasure journal state directory is invalid")
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not parent.is_dir() or parent.is_symlink():
                raise ErasureJournalError("Erasure journal state directory is invalid")
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ErasureJournalError("Erasure journal state file is invalid")
            with temporary_path.open("xb") as temporary:
                os.chmod(temporary_path, 0o600)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(path)
            os.chmod(path, 0o600)
            self._fsync_directory(parent)
        except ErasureJournalError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise ErasureJournalError("Erasure journal state could not be stored durably") from exc

    @classmethod
    def _empty_checkpoint(cls, continuity_id: str) -> JournalCheckpoint:
        return JournalCheckpoint(
            schema_version=_STATE_SCHEMA_VERSION,
            continuity_id=continuity_id,
            generation=0,
            entry_count=0,
            journal_size=0,
            chain_digest=cls._genesis_digest(continuity_id),
            tail_size=0,
            tail_digest=cls._digest(b""),
        )

    @staticmethod
    def _same_checkpoint(left: JournalCheckpoint, right: JournalCheckpoint) -> bool:
        return left == right

    @staticmethod
    def _same_physical_state(left: JournalCheckpoint, right: JournalCheckpoint) -> bool:
        return (
            left.continuity_id == right.continuity_id
            and left.entry_count == right.entry_count
            and left.journal_size == right.journal_size
            and left.chain_digest == right.chain_digest
            and left.tail_size == right.tail_size
            and left.tail_digest == right.tail_digest
        )

    @staticmethod
    def _digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def _genesis_digest(cls, continuity_id: str) -> str:
        return cls._digest(_STATE_DOMAIN + b"\0genesis\0" + continuity_id.encode("ascii"))

    @classmethod
    def _advance_chain(cls, chain_digest: str, encoded: bytes) -> str:
        return cls._digest(
            _STATE_DOMAIN
            + b"\0entry\0"
            + bytes.fromhex(chain_digest)
            + len(encoded).to_bytes(8, "big")
            + encoded
        )

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor: int | None = None
        try:
            descriptor = os.open(directory, os.O_RDONLY)
            os.fsync(descriptor)
        except OSError as exc:
            raise ErasureJournalError("Erasure journal directory could not be synchronized") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _encode(tombstone: ErasureJournalEntry) -> bytes:
        encoded = (
            json.dumps(
                asdict(tombstone),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > MAX_TOMBSTONE_BYTES:
            raise ErasureJournalError("Erasure intent contains too many identifiers")
        return encoded

    @classmethod
    def _decode(cls, line: bytes) -> ErasureJournalEntry:
        try:
            raw = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErasureJournalError("Erasure journal contains malformed JSON") from exc
        if not isinstance(raw, dict):
            raise ErasureJournalError("Erasure journal contains an invalid record schema")
        if raw.get("kind") == "provider_transcript":
            if set(raw) != {
                "schema_version",
                "event_id",
                "kind",
                "created_at",
                "provider",
                "transcript_id",
            }:
                raise ErasureJournalError("Erasure journal contains an invalid record schema")
            entry: ErasureJournalEntry = ProviderTranscriptErasureTombstone(
                schema_version=raw["schema_version"],
                event_id=raw["event_id"],
                kind=raw["kind"],
                created_at=raw["created_at"],
                provider=raw["provider"],
                transcript_id=raw["transcript_id"],
            )
        elif raw.get("kind") == "orphan_workspace":
            if set(raw) != {
                "schema_version",
                "event_id",
                "kind",
                "created_at",
                "job_ids",
            }:
                raise ErasureJournalError("Erasure journal contains an invalid record schema")
            entry = OrphanWorkspaceErasureTombstone(
                schema_version=raw["schema_version"],
                event_id=raw["event_id"],
                kind=raw["kind"],
                created_at=raw["created_at"],
                job_ids=raw["job_ids"],
            )
        elif raw.get("kind") == "job_terminal":
            if set(raw) != {
                "schema_version",
                "event_id",
                "kind",
                "created_at",
                "user_id",
                "job_ids",
                "terminal_status",
            }:
                raise ErasureJournalError("Erasure journal contains an invalid record schema")
            entry = JobTerminalErasureTombstone(
                schema_version=raw["schema_version"],
                event_id=raw["event_id"],
                kind=raw["kind"],
                created_at=raw["created_at"],
                user_id=raw["user_id"],
                job_ids=raw["job_ids"],
                terminal_status=raw["terminal_status"],
            )
        else:
            if set(raw) != {
                "schema_version",
                "event_id",
                "kind",
                "created_at",
                "user_id",
                "job_ids",
            }:
                raise ErasureJournalError("Erasure journal contains an invalid record schema")
            entry = ErasureTombstone(
                schema_version=raw["schema_version"],
                event_id=raw["event_id"],
                kind=raw["kind"],
                created_at=raw["created_at"],
                user_id=raw["user_id"],
                job_ids=raw["job_ids"],
            )
        cls._validate(entry)
        return entry

    @staticmethod
    def _validate(tombstone: ErasureJournalEntry) -> None:
        if tombstone.schema_version != 1:
            raise ErasureJournalError("Erasure journal schema version is unsupported")
        if not isinstance(tombstone.event_id, str) or not _EVENT_ID.fullmatch(tombstone.event_id):
            raise ErasureJournalError("Erasure journal event identifier is invalid")
        if type(tombstone.created_at) is not int or tombstone.created_at <= 0:
            raise ErasureJournalError("Erasure journal timestamp is invalid")
        if isinstance(tombstone, ProviderTranscriptErasureTombstone):
            if tombstone.kind != "provider_transcript" or tombstone.provider != "elevenlabs":
                raise ErasureJournalError("Erasure journal provider event is invalid")
            if not isinstance(tombstone.transcript_id, str) or not _IDENTIFIER.fullmatch(
                tombstone.transcript_id,
            ):
                raise ErasureJournalError("Erasure journal provider transcript identifier is invalid")
            return
        if isinstance(tombstone, OrphanWorkspaceErasureTombstone):
            if tombstone.kind != "orphan_workspace":
                raise ErasureJournalError("Erasure journal orphan workspace event is invalid")
            if not isinstance(tombstone.job_ids, list) or not tombstone.job_ids or any(
                not isinstance(job_id, str) or not _IDENTIFIER.fullmatch(job_id)
                for job_id in tombstone.job_ids
            ):
                raise ErasureJournalError("Erasure journal orphan workspace identifiers are invalid")
            if tombstone.job_ids != sorted(set(tombstone.job_ids)):
                raise ErasureJournalError("Erasure journal job identifiers are not canonical")
            return
        if isinstance(tombstone, JobTerminalErasureTombstone):
            if (
                tombstone.kind != "job_terminal"
                or tombstone.terminal_status not in {"cancelled", "failed"}
            ):
                raise ErasureJournalError("Erasure journal terminal job event is invalid")
            if not isinstance(tombstone.user_id, str) or not _IDENTIFIER.fullmatch(
                tombstone.user_id,
            ):
                raise ErasureJournalError("Erasure journal account identifier is invalid")
            if not isinstance(tombstone.job_ids, list) or not tombstone.job_ids or any(
                not isinstance(job_id, str) or not _IDENTIFIER.fullmatch(job_id)
                for job_id in tombstone.job_ids
            ):
                raise ErasureJournalError("Erasure journal terminal job identifiers are invalid")
            if tombstone.job_ids != sorted(set(tombstone.job_ids)):
                raise ErasureJournalError("Erasure journal job identifiers are not canonical")
            return
        if tombstone.kind not in _ALLOWED_KINDS:
            raise ErasureJournalError("Erasure journal event kind is invalid")
        if not isinstance(tombstone.user_id, str) or not _IDENTIFIER.fullmatch(tombstone.user_id):
            raise ErasureJournalError("Erasure journal account identifier is invalid")
        if not isinstance(tombstone.job_ids, list) or any(
            not isinstance(job_id, str) or not _IDENTIFIER.fullmatch(job_id)
            for job_id in tombstone.job_ids
        ):
            raise ErasureJournalError("Erasure journal job identifiers are invalid")
        if tombstone.job_ids != sorted(set(tombstone.job_ids)):
            raise ErasureJournalError("Erasure journal job identifiers are not canonical")
        if tombstone.kind in {"workspace", "job"} and not tombstone.job_ids:
            raise ErasureJournalError("Erasure journal job event is empty")


def configured_erasure_journal() -> ErasureJournal:
    """Build the configured journal and reject restored-media co-location."""
    root = settings.erasure_journal_dir.expanduser().resolve()
    data_dir = settings.data_dir.expanduser().resolve()
    if (
        root == Path(root.anchor)
        or root == data_dir
        or root.is_relative_to(data_dir)
        or data_dir.is_relative_to(root)
    ):
        raise ErasureJournalError("Erasure journal must be isolated from application media")
    configured_anchor = settings.erasure_journal_anchor_path
    anchor_path = configured_anchor.expanduser().resolve() if configured_anchor is not None else None
    if not settings.is_dev and anchor_path is None:
        raise ErasureJournalError(
            "Production erasure journal external anchor path is required",
        )
    if anchor_path is not None and (
        anchor_path == Path(anchor_path.anchor)
        or anchor_path == root
        or anchor_path.is_relative_to(root)
        or anchor_path == data_dir
        or anchor_path.is_relative_to(data_dir)
        or data_dir.is_relative_to(anchor_path)
    ):
        raise ErasureJournalError(
            "Erasure journal external anchor must be isolated from journal and media storage",
        )
    return ErasureJournal(
        root,
        retention_days=settings.erasure_journal_retention_days,
        expected_continuity_id=(settings.erasure_journal_continuity_id or None),
        anchor_path=anchor_path,
    )
