"""Checkpoint persistence and integrity primitives for the erasure journal."""

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from .erasure_journal_types import (
    CONTINUITY_ID,
    DIGEST,
    MAX_JOURNAL_BYTES,
    MAX_STATE_BYTES,
    MAX_TOMBSTONE_BYTES,
    STATE_DOMAIN,
    STATE_SCHEMA_VERSION,
    ErasureJournalError,
    JournalCheckpoint,
    PendingJournalMutation,
)


class ErasureJournalStorageMixin:
    """Durable storage helpers mixed into the journal orchestrator."""

    pending_path: Path
    checkpoint_path: Path
    anchor_path: Path | None
    root: Path

    def _read_checkpoint_unlocked(self, path: Path, *, label: str) -> JournalCheckpoint:
        try:
            if path.is_symlink() or not path.is_file():
                raise ErasureJournalError(f"Erasure journal {label} is unavailable")
            raw_bytes = path.read_bytes()
            if len(raw_bytes) > MAX_STATE_BYTES:
                raise ErasureJournalError(f"Erasure journal {label} is invalid")
            raw = json.loads(raw_bytes)
        except ErasureJournalError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErasureJournalError(f"Erasure journal {label} could not be read") from exc
        checkpoint = self._checkpoint_from_mapping(raw, label=label)
        return checkpoint

    def _read_pending_unlocked(self) -> PendingJournalMutation:
        try:
            if self.pending_path.is_symlink() or not self.pending_path.is_file():
                raise ErasureJournalError("Erasure journal pending state is invalid")
            raw_bytes = self.pending_path.read_bytes()
            if len(raw_bytes) > MAX_STATE_BYTES:
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
        if pending.schema_version != STATE_SCHEMA_VERSION or pending.operation not in {
            "append",
            "replace",
        }:
            raise ErasureJournalError("Erasure journal pending state is invalid")
        return pending

    def _checkpoint_from_mapping(self, raw: object, *, label: str) -> JournalCheckpoint:
        expected_keys = {
            "schema_version",
            "continuity_id",
            "generation",
            "entry_count",
            "journal_size",
            "chain_digest",
            "tail_size",
            "tail_digest",
        }
        if not isinstance(raw, dict) or set(raw) != expected_keys:
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
            checkpoint.schema_version != STATE_SCHEMA_VERSION
            or not isinstance(checkpoint.continuity_id, str)
            or CONTINUITY_ID.fullmatch(checkpoint.continuity_id) is None
            or type(checkpoint.generation) is not int
            or checkpoint.generation < 0
            or type(checkpoint.entry_count) is not int
            or checkpoint.entry_count < 0
            or type(checkpoint.journal_size) is not int
            or checkpoint.journal_size < 0
            or checkpoint.journal_size > MAX_JOURNAL_BYTES
            or not isinstance(checkpoint.chain_digest, str)
            or DIGEST.fullmatch(checkpoint.chain_digest) is None
            or type(checkpoint.tail_size) is not int
            or checkpoint.tail_size < 0
            or checkpoint.tail_size > MAX_TOMBSTONE_BYTES
            or not isinstance(checkpoint.tail_digest, str)
            or DIGEST.fullmatch(checkpoint.tail_digest) is None
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
        self._write_private_bytes_atomic(self.checkpoint_path, self._encode_checkpoint(checkpoint))

    def _write_anchor_unlocked(self, checkpoint: JournalCheckpoint) -> None:
        if self.anchor_path is not None:
            self._write_private_bytes_atomic(self.anchor_path, self._encode_checkpoint(checkpoint))

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
            schema_version=STATE_SCHEMA_VERSION,
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
        return cls._digest(STATE_DOMAIN + b"\0genesis\0" + continuity_id.encode("ascii"))

    @classmethod
    def _advance_chain(cls, chain_digest: str, encoded: bytes) -> str:
        return cls._digest(
            STATE_DOMAIN + b"\0entry\0" + bytes.fromhex(chain_digest) + len(encoded).to_bytes(8, "big") + encoded
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
