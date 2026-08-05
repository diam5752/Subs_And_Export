"""Durable privacy tombstones that survive database and media restores."""

from __future__ import annotations

import fcntl
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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}$")
_JOURNAL_FILENAME = "tombstones.jsonl"
_LOCK_FILENAME = ".journal.lock"
_CONTINUITY_FILENAME = ".continuity-id"
_CONTINUITY_ID = re.compile(r"^[0-9a-f]{64}$")
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


ErasureJournalEntry = (
    ErasureTombstone
    | ProviderTranscriptErasureTombstone
    | OrphanWorkspaceErasureTombstone
)


class ErasureJournal:
    """Append-only, fsync-backed erasure intent journal."""

    def __init__(
        self,
        root: Path,
        *,
        retention_days: int,
        expected_continuity_id: str | None = None,
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
        self.journal_path = root / _JOURNAL_FILENAME
        self.lock_path = root / _LOCK_FILENAME
        self.continuity_path = root / _CONTINUITY_FILENAME

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

    def _append_entry(self, tombstone: ErasureJournalEntry) -> None:
        self._validate(tombstone)
        encoded = self._encode(tombstone)
        with self._exclusive_lock():
            if self.journal_path.is_symlink():
                raise ErasureJournalError("Erasure journal file is invalid")
            created = not self.journal_path.exists()
            try:
                if not created:
                    # Refuse to acknowledge a new privacy action on top of a
                    # corrupt or incomplete journal that could not be replayed.
                    self._read_unlocked()
                existing_size = self.journal_path.stat().st_size if not created else 0
                if existing_size + len(encoded) > MAX_JOURNAL_BYTES:
                    raise ErasureJournalError("Erasure journal exceeds its safe size limit")
                with self.journal_path.open("ab") as journal:
                    os.chmod(self.journal_path, 0o600)
                    journal.write(encoded)
                    journal.flush()
                    os.fsync(journal.fileno())
                if created:
                    self._fsync_root()
            except OSError as exc:
                raise ErasureJournalError("Erasure intent could not be stored durably") from exc

    def read_all(self) -> list[ErasureJournalEntry]:
        """Read and strictly validate every retained tombstone."""
        with self._exclusive_lock():
            return self._read_unlocked()

    def prune_expired(self, *, now: int | None = None) -> int:
        """Prune only entries older than the configured backup-safe window."""
        current_time = int(time.time()) if now is None else now
        if type(current_time) is not int or current_time <= 0:
            raise ValueError("Erasure journal cutoff must be a positive integer")
        cutoff = current_time - (self.retention_days * 86_400)
        with self._exclusive_lock():
            entries = self._read_unlocked()
            retained = [entry for entry in entries if entry.created_at >= cutoff]
            removed = len(entries) - len(retained)
            if removed:
                self._replace_unlocked(retained)
            return removed

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self._ensure_root()
        try:
            if self.lock_path.is_symlink():
                raise ErasureJournalError("Erasure journal lock file is invalid")
            with self.lock_path.open("a+b") as lock_file:
                os.chmod(self.lock_path, 0o600)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    self._verify_continuity_unlocked()
                    yield
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

    def _verify_continuity_unlocked(self) -> None:
        """Reject a missing or replaced production journal volume."""
        expected = self.expected_continuity_id
        if expected is None:
            return
        try:
            if self.continuity_path.is_symlink() or not self.continuity_path.is_file():
                raise ErasureJournalError("Erasure journal continuity is unavailable")
            raw = self.continuity_path.read_bytes()
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal continuity could not be read") from exc
        if raw not in {expected.encode("ascii"), f"{expected}\n".encode("ascii")}:
            raise ErasureJournalError("Erasure journal continuity does not match this host")

    def _read_unlocked(self) -> list[ErasureJournalEntry]:
        if self.journal_path.is_symlink():
            raise ErasureJournalError("Erasure journal file is invalid")
        if not self.journal_path.exists():
            return []
        if not self.journal_path.is_file():
            raise ErasureJournalError("Erasure journal file is invalid")
        try:
            if self.journal_path.stat().st_size > MAX_JOURNAL_BYTES:
                raise ErasureJournalError("Erasure journal exceeds its safe size limit")
            entries: list[ErasureJournalEntry] = []
            event_ids: set[str] = set()
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
            return entries
        except ErasureJournalError:
            raise
        except OSError as exc:
            raise ErasureJournalError("Erasure journal could not be read") from exc

    def _replace_unlocked(self, entries: list[ErasureJournalEntry]) -> None:
        temporary_path = self.root / f".{_JOURNAL_FILENAME}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary_path.open("xb") as temporary:
                os.chmod(temporary_path, 0o600)
                for entry in entries:
                    temporary.write(self._encode(entry))
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(self.journal_path)
            os.chmod(self.journal_path, 0o600)
            self._fsync_root()
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise ErasureJournalError("Erasure journal could not be pruned durably") from exc

    def _fsync_root(self) -> None:
        descriptor: int | None = None
        try:
            descriptor = os.open(self.root, os.O_RDONLY)
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
            if not tombstone.job_ids or any(
                not isinstance(job_id, str) or not _IDENTIFIER.fullmatch(job_id)
                for job_id in tombstone.job_ids
            ):
                raise ErasureJournalError("Erasure journal orphan workspace identifiers are invalid")
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
    if root == Path(root.anchor) or root == data_dir or root.is_relative_to(data_dir) or data_dir.is_relative_to(root):
        raise ErasureJournalError("Erasure journal must be isolated from application media")
    return ErasureJournal(
        root,
        retention_days=settings.erasure_journal_retention_days,
        expected_continuity_id=(settings.erasure_journal_continuity_id or None),
    )
