"""Encoding and schema validation for erasure journal entries."""

import json
from dataclasses import asdict

from .erasure_journal_types import (
    ALLOWED_KINDS,
    EVENT_ID,
    IDENTIFIER,
    MAX_TOMBSTONE_BYTES,
    ErasureJournalEntry,
    ErasureJournalError,
    ErasureTombstone,
    JobTerminalErasureTombstone,
    OrphanWorkspaceErasureTombstone,
    ProviderTranscriptErasureTombstone,
)


class ErasureJournalCodecMixin:
    """Stateless codec methods used by the journal orchestrator."""

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
            if set(raw) != {"schema_version", "event_id", "kind", "created_at", "job_ids"}:
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
        ErasureJournalCodecMixin._validate_common(tombstone)
        if isinstance(tombstone, ProviderTranscriptErasureTombstone):
            ErasureJournalCodecMixin._validate_provider_transcript(tombstone)
            return
        if isinstance(tombstone, OrphanWorkspaceErasureTombstone):
            ErasureJournalCodecMixin._validate_orphan_workspace(tombstone)
            return
        if isinstance(tombstone, JobTerminalErasureTombstone):
            ErasureJournalCodecMixin._validate_terminal_job(tombstone)
            return
        ErasureJournalCodecMixin._validate_user_job_entry(tombstone)

    @staticmethod
    def _validate_common(tombstone: ErasureJournalEntry) -> None:
        if tombstone.schema_version != 1:
            raise ErasureJournalError("Erasure journal schema version is unsupported")
        if not isinstance(tombstone.event_id, str) or not EVENT_ID.fullmatch(tombstone.event_id):
            raise ErasureJournalError("Erasure journal event identifier is invalid")
        if type(tombstone.created_at) is not int or tombstone.created_at <= 0:
            raise ErasureJournalError("Erasure journal timestamp is invalid")

    @staticmethod
    def _validate_provider_transcript(tombstone: ProviderTranscriptErasureTombstone) -> None:
        if tombstone.kind != "provider_transcript" or tombstone.provider != "elevenlabs":
            raise ErasureJournalError("Erasure journal provider event is invalid")
        if not isinstance(tombstone.transcript_id, str) or not IDENTIFIER.fullmatch(
            tombstone.transcript_id,
        ):
            raise ErasureJournalError("Erasure journal provider transcript identifier is invalid")

    @staticmethod
    def _validate_orphan_workspace(tombstone: OrphanWorkspaceErasureTombstone) -> None:
        if tombstone.kind != "orphan_workspace":
            raise ErasureJournalError("Erasure journal orphan workspace event is invalid")
        ErasureJournalCodecMixin._validate_job_ids(tombstone.job_ids, "orphan workspace")

    @staticmethod
    def _validate_terminal_job(tombstone: JobTerminalErasureTombstone) -> None:
        if tombstone.kind != "job_terminal" or tombstone.terminal_status not in {
            "cancelled",
            "failed",
        }:
            raise ErasureJournalError("Erasure journal terminal job event is invalid")
        ErasureJournalCodecMixin._validate_account_id(tombstone.user_id)
        ErasureJournalCodecMixin._validate_job_ids(tombstone.job_ids, "terminal job")

    @staticmethod
    def _validate_user_job_entry(tombstone: ErasureTombstone) -> None:
        if tombstone.kind not in ALLOWED_KINDS:
            raise ErasureJournalError("Erasure journal event kind is invalid")
        ErasureJournalCodecMixin._validate_account_id(tombstone.user_id)
        if not isinstance(tombstone.job_ids, list) or any(
            not isinstance(job_id, str) or not IDENTIFIER.fullmatch(job_id) for job_id in tombstone.job_ids
        ):
            raise ErasureJournalError("Erasure journal job identifiers are invalid")
        if tombstone.job_ids != sorted(set(tombstone.job_ids)):
            raise ErasureJournalError("Erasure journal job identifiers are not canonical")
        if tombstone.kind in {"workspace", "job"} and not tombstone.job_ids:
            raise ErasureJournalError("Erasure journal job event is empty")

    @staticmethod
    def _validate_account_id(user_id: object) -> None:
        if not isinstance(user_id, str) or not IDENTIFIER.fullmatch(user_id):
            raise ErasureJournalError("Erasure journal account identifier is invalid")

    @staticmethod
    def _validate_job_ids(job_ids: object, label: str) -> None:
        if (
            not isinstance(job_ids, list)
            or not job_ids
            or any(not isinstance(job_id, str) or not IDENTIFIER.fullmatch(job_id) for job_id in job_ids)
        ):
            raise ErasureJournalError(f"Erasure journal {label} identifiers are invalid")
        if job_ids != sorted(set(job_ids)):
            raise ErasureJournalError("Erasure journal job identifiers are not canonical")
