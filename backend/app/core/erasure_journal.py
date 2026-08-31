"""Durable privacy tombstones that survive database and media restores."""

from __future__ import annotations

import fcntl
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings
from .erasure_journal_codec import ErasureJournalCodecMixin
from .erasure_journal_storage import ErasureJournalStorageMixin
from .erasure_journal_types import (
    CHECKPOINT_FILENAME as _CHECKPOINT_FILENAME,
)
from .erasure_journal_types import (
    CONTINUITY_FILENAME as _CONTINUITY_FILENAME,
)
from .erasure_journal_types import (
    CONTINUITY_ID as _CONTINUITY_ID,
)
from .erasure_journal_types import (
    JOURNAL_FILENAME as _JOURNAL_FILENAME,
)
from .erasure_journal_types import (
    LOCK_FILENAME as _LOCK_FILENAME,
)
from .erasure_journal_types import (
    MAX_JOURNAL_BYTES,
    MAX_TOMBSTONE_BYTES,
    JournalCheckpoint,
    PendingJournalMutation,
    ProviderName,
)
from .erasure_journal_types import (
    PENDING_FILENAME as _PENDING_FILENAME,
)
from .erasure_journal_types import (
    STATE_SCHEMA_VERSION as _STATE_SCHEMA_VERSION,
)
from .erasure_journal_types import (
    ErasureJournalEntry as ErasureJournalEntry,
)
from .erasure_journal_types import (
    ErasureJournalError as ErasureJournalError,
)
from .erasure_journal_types import (
    ErasureTombstone as ErasureTombstone,
)
from .erasure_journal_types import (
    JobTerminalErasureTombstone as JobTerminalErasureTombstone,
)
from .erasure_journal_types import (
    JobTerminalStatus as JobTerminalStatus,
)
from .erasure_journal_types import (
    OrphanWorkspaceErasureTombstone as OrphanWorkspaceErasureTombstone,
)
from .erasure_journal_types import (
    ProviderTranscriptErasureTombstone as ProviderTranscriptErasureTombstone,
)
from .erasure_journal_types import (
    TombstoneKind as TombstoneKind,
)


class ErasureJournal(ErasureJournalStorageMixin, ErasureJournalCodecMixin):
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
        if (
            expected_continuity_id is not None
            and _CONTINUITY_ID.fullmatch(
                expected_continuity_id,
            )
            is None
        ):
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

        state_exists = journal_exists or checkpoint_exists or (self.anchor_path is not None and anchor_exists)
        if explicit:
            self._initialize_explicit_unlocked(continuity_id, state_exists=state_exists)
            return
        if self.expected_continuity_id is not None:
            self._raise_configured_initialization_error(
                journal_exists=journal_exists,
                checkpoint_exists=checkpoint_exists,
                anchor_exists=anchor_exists,
            )
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

    def _initialize_explicit_unlocked(self, continuity_id: str, *, state_exists: bool) -> None:
        if state_exists:
            raise ErasureJournalError("Erasure journal is only partially initialized")
        self._create_empty_state_unlocked(continuity_id)

    @staticmethod
    def _raise_configured_initialization_error(
        *,
        journal_exists: bool,
        checkpoint_exists: bool,
        anchor_exists: bool,
    ) -> None:
        if checkpoint_exists and anchor_exists and not journal_exists:
            raise ErasureJournalError("Erasure journal ledger is unavailable")
        if journal_exists and anchor_exists and not checkpoint_exists:
            raise ErasureJournalError("Erasure journal checkpoint is unavailable")
        if journal_exists and checkpoint_exists and not anchor_exists:
            raise ErasureJournalError("Erasure journal external anchor is unavailable")
        raise ErasureJournalError("Erasure journal has not been initialized")

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
            self.anchor_path.is_symlink() or (self.anchor_path.exists() and not self.anchor_path.is_file())
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
        if not any(self._same_checkpoint(existing_checkpoint, allowed) for allowed in allowed_checkpoints):
            raise ErasureJournalError("Erasure journal checkpoint conflicts with pending state")
        if self.anchor_path is not None:
            existing_anchor = self._read_checkpoint_unlocked(
                self.anchor_path,
                label="external anchor",
            )
            if not any(self._same_checkpoint(existing_anchor, allowed) for allowed in allowed_checkpoints):
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


def configured_erasure_journal() -> ErasureJournal:
    """Build the configured journal and reject restored-media co-location."""
    root = settings.erasure_journal_dir.expanduser().resolve()
    data_dir = settings.data_dir.expanduser().resolve()
    if root == Path(root.anchor) or root == data_dir or root.is_relative_to(data_dir) or data_dir.is_relative_to(root):
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
