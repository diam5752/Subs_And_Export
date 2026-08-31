"""Data contracts and immutable constants for the erasure journal."""

import re
from dataclasses import dataclass
from typing import Literal

TombstoneKind = Literal["workspace", "job", "account"]
ALLOWED_KINDS = frozenset({"workspace", "job", "account"})
ProviderTombstoneKind = Literal["provider_transcript"]
ProviderName = Literal["elevenlabs"]
OrphanTombstoneKind = Literal["orphan_workspace"]
JobTerminalTombstoneKind = Literal["job_terminal"]
JobTerminalStatus = Literal["cancelled", "failed"]
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
EVENT_ID = re.compile(r"^[0-9a-f]{32}$")
JOURNAL_FILENAME = "tombstones.jsonl"
LOCK_FILENAME = ".journal.lock"
CONTINUITY_FILENAME = ".continuity-id"
CHECKPOINT_FILENAME = ".journal-checkpoint.json"
PENDING_FILENAME = ".journal-pending.json"
CONTINUITY_ID = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
STATE_SCHEMA_VERSION = 1
STATE_DOMAIN = b"gsubs-erasure-journal-state/v1"
MAX_STATE_BYTES = 16 * 1024
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
