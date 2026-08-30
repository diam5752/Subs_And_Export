"""Durable ownership markers written before any per-job media bytes."""

from __future__ import annotations

import fcntl
import hashlib
import heapq
import json
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from backend.app.core.erasure_journal import ErasureJournalError

_REGISTRY_DIR = ".workspace-ownership"
_REGISTRY_LOCK = ".registry.lock"
_MARKER_SUFFIX = ".json"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MARKER_FILENAME = re.compile(r"^[0-9a-f]{64}\.json$")
_STALE_TEMP_FILENAME = re.compile(
    r"^\.[0-9a-f]{64}\.json\.[0-9a-f]{32}\.tmp$",
)
_MAX_MARKER_BYTES = 4 * 1024


class WorkspaceOwnershipError(ErasureJournalError):
    """Raised when durable workspace ownership cannot be trusted."""


class WorkspaceOwnershipConflictError(WorkspaceOwnershipError):
    """Raised when one job ID is already attributed to another account."""


@dataclass(frozen=True, slots=True)
class WorkspaceOwnershipMarker:
    schema_version: int
    job_id: str
    user_id: str
    created_at: int


@dataclass(frozen=True, slots=True)
class WorkspaceOwnershipMarkerPage:
    markers: list[WorkspaceOwnershipMarker]
    next_cursor: str | None


def record_workspace_ownership(
    *,
    data_dir: Path,
    job_id: str,
    user_id: str,
    now: int | None = None,
) -> WorkspaceOwnershipMarker:
    """Persist ownership before the caller creates or copies any media."""
    _validate_identifier(job_id, label="job")
    _validate_identifier(user_id, label="account")
    marker = WorkspaceOwnershipMarker(
        schema_version=1,
        job_id=job_id,
        user_id=user_id,
        created_at=int(time.time()) if now is None else now,
    )
    _validate_marker(marker)
    filename = _marker_filename(job_id)

    with _locked_registry(data_dir=data_dir, create=True) as directory_fd:
        if directory_fd is None:
            raise WorkspaceOwnershipError("Workspace ownership registry is unavailable")
        existing = _read_marker(directory_fd=directory_fd, filename=filename)
        if existing is not None:
            if existing.job_id != job_id or existing.user_id != user_id:
                raise WorkspaceOwnershipConflictError(
                    "Workspace is already attributed to another account",
                )
            return existing

        encoded = (
            json.dumps(
                asdict(marker),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > _MAX_MARKER_BYTES:
            raise WorkspaceOwnershipError("Workspace ownership marker is too large")
        temporary = f".{filename}.{uuid.uuid4().hex}.tmp"
        marker_fd: int | None = None
        try:
            marker_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            os.fchmod(marker_fd, 0o600)
            _write_all(marker_fd, encoded)
            os.fsync(marker_fd)
            os.close(marker_fd)
            marker_fd = None
            os.rename(
                temporary,
                filename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        except OSError as exc:
            raise WorkspaceOwnershipError(
                "Workspace ownership could not be stored durably",
            ) from exc
        finally:
            if marker_fd is not None:
                os.close(marker_fd)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
    return marker


def list_owned_workspace_ids(*, data_dir: Path, user_id: str) -> list[str]:
    """List exact job IDs whose durable marker names this account."""
    _validate_identifier(user_id, label="account")
    owned: list[str] = []
    with _locked_registry(data_dir=data_dir, create=False) as directory_fd:
        if directory_fd is None:
            return owned
        for filename in _validated_marker_filenames(directory_fd):
            marker = _read_marker(directory_fd=directory_fd, filename=filename)
            if marker is None:
                raise WorkspaceOwnershipError(
                    "Workspace ownership registry changed while being read",
                )
            if marker.user_id == user_id:
                owned.append(marker.job_id)
    return sorted(owned)


def list_workspace_ownership_markers(
    *,
    data_dir: Path,
    limit: int = 100,
    after: str | None = None,
) -> WorkspaceOwnershipMarkerPage:
    """Return one validated, filename-cursor page for bounded retention work."""
    if type(limit) is not int or limit <= 0 or limit > 1_000:
        raise ValueError("Workspace ownership page limit must be between 1 and 1000")
    if after is not None and _MARKER_FILENAME.fullmatch(after) is None:
        raise ValueError("Workspace ownership page cursor is invalid")
    with _locked_registry(data_dir=data_dir, create=False) as directory_fd:
        if directory_fd is None:
            return WorkspaceOwnershipMarkerPage(markers=[], next_cursor=None)
        selected_with_sentinel = heapq.nsmallest(
            limit + 1,
            (filename for filename in _validated_marker_filenames(directory_fd) if after is None or filename > after),
        )
        selected = selected_with_sentinel[:limit]
        markers: list[WorkspaceOwnershipMarker] = []
        for filename in selected:
            marker = _read_marker(directory_fd=directory_fd, filename=filename)
            if marker is None:
                raise WorkspaceOwnershipError(
                    "Workspace ownership registry changed while being read",
                )
            markers.append(marker)
        next_cursor = selected[-1] if selected and len(selected_with_sentinel) > len(selected) else None
        return WorkspaceOwnershipMarkerPage(
            markers=markers,
            next_cursor=next_cursor,
        )


def get_workspace_owner(*, data_dir: Path, job_id: str) -> str | None:
    """Return the durable owner of one exact workspace, when recorded."""
    _validate_identifier(job_id, label="job")
    with _locked_registry(data_dir=data_dir, create=False) as directory_fd:
        if directory_fd is None:
            return None
        marker = _read_marker(
            directory_fd=directory_fd,
            filename=_marker_filename(job_id),
        )
        return marker.user_id if marker is not None else None


def remove_workspace_ownership_after_verified_cleanup(
    *,
    data_dir: Path,
    job_id: str,
    expected_user_id: str | None = None,
) -> bool:
    """Remove a marker only after the caller verified exact media absence."""
    _validate_identifier(job_id, label="job")
    if expected_user_id is not None:
        _validate_identifier(expected_user_id, label="account")
    filename = _marker_filename(job_id)
    with _locked_registry(data_dir=data_dir, create=False) as directory_fd:
        if directory_fd is None:
            return False
        marker = _read_marker(directory_fd=directory_fd, filename=filename)
        if marker is None:
            return False
        if expected_user_id is not None and marker.user_id != expected_user_id:
            raise WorkspaceOwnershipConflictError(
                "Workspace ownership changed before cleanup",
            )
        try:
            os.unlink(filename, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError as exc:
            raise WorkspaceOwnershipError(
                "Workspace ownership cleanup could not be stored durably",
            ) from exc
    return True


@contextmanager
def _locked_registry(
    *,
    data_dir: Path,
    create: bool,
) -> Iterator[int | None]:
    root = data_dir.resolve() / _REGISTRY_DIR
    if not _prepare_registry_root(root, create=create):
        yield None
        return

    directory_fd: int | None = None
    lock_fd: int | None = None
    locked = False
    try:
        directory_fd = _open_registry_directory(root)
        if create:
            _sync_registry_parent(root)
        lock_fd = _open_registry_lock(directory_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        locked = True
        _scavenge_stale_temporary_markers(directory_fd)
        yield directory_fd
    except WorkspaceOwnershipError:
        raise
    except OSError as exc:
        raise WorkspaceOwnershipError(
            "Workspace ownership registry is unavailable",
        ) from exc
    finally:
        if locked and lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if lock_fd is not None:
            os.close(lock_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _prepare_registry_root(root: Path, *, create: bool) -> bool:
    if create:
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceOwnershipError("Workspace ownership registry is unavailable") from exc
        return True
    if root.exists():
        return True
    if root.is_symlink():
        raise WorkspaceOwnershipError("Workspace ownership registry is invalid")
    return False


def _open_registry_directory(root: Path) -> int:
    directory_fd = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise WorkspaceOwnershipError("Workspace ownership registry is invalid")
        os.fchmod(directory_fd, 0o700)
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def _sync_registry_parent(root: Path) -> None:
    parent_fd = os.open(
        root.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        if not stat.S_ISDIR(os.fstat(parent_fd).st_mode):
            raise WorkspaceOwnershipError("Workspace ownership registry parent is invalid")
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _open_registry_lock(directory_fd: int) -> int:
    lock_fd = os.open(
        _REGISTRY_LOCK,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise WorkspaceOwnershipError("Workspace ownership registry lock is invalid")
        os.fchmod(lock_fd, 0o600)
        return lock_fd
    except BaseException:
        os.close(lock_fd)
        raise


def _read_marker(
    *,
    directory_fd: int,
    filename: str,
) -> WorkspaceOwnershipMarker | None:
    marker_fd: int | None = None
    try:
        marker_fd = os.open(
            filename,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise WorkspaceOwnershipError(
            "Workspace ownership marker is unavailable",
        ) from exc
    try:
        marker_stat = os.fstat(marker_fd)
        if not stat.S_ISREG(marker_stat.st_mode) or marker_stat.st_size <= 0 or marker_stat.st_size > _MAX_MARKER_BYTES:
            raise WorkspaceOwnershipError("Workspace ownership marker is invalid")
        encoded = b""
        while len(encoded) <= _MAX_MARKER_BYTES:
            chunk = os.read(marker_fd, _MAX_MARKER_BYTES + 1 - len(encoded))
            if not chunk:
                break
            encoded += chunk
        if len(encoded) > _MAX_MARKER_BYTES:
            raise WorkspaceOwnershipError("Workspace ownership marker is invalid")
    finally:
        os.close(marker_fd)
    try:
        raw = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceOwnershipError("Workspace ownership marker is invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "job_id",
        "user_id",
        "created_at",
    }:
        raise WorkspaceOwnershipError("Workspace ownership marker is invalid")
    marker = WorkspaceOwnershipMarker(
        schema_version=raw["schema_version"],
        job_id=raw["job_id"],
        user_id=raw["user_id"],
        created_at=raw["created_at"],
    )
    _validate_marker(marker)
    if filename != _marker_filename(marker.job_id):
        raise WorkspaceOwnershipError("Workspace ownership marker is misplaced")
    return marker


def _scavenge_stale_temporary_markers(directory_fd: int) -> None:
    """Retire only our crash-residue temp files under the registry lock."""
    removed = False
    try:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                filename = entry.name
                if _STALE_TEMP_FILENAME.fullmatch(filename) is None:
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    os.unlink(filename, dir_fd=directory_fd)
                    removed = True
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise WorkspaceOwnershipError(
                        "Workspace ownership temp cleanup failed",
                    ) from exc
    except WorkspaceOwnershipError:
        raise
    except OSError as exc:
        raise WorkspaceOwnershipError(
            "Workspace ownership registry could not be read",
        ) from exc
    if removed:
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            raise WorkspaceOwnershipError(
                "Workspace ownership temp cleanup was not durable",
            ) from exc


def _validated_marker_filenames(directory_fd: int) -> Iterator[str]:
    try:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                filename = entry.name
                if filename == _REGISTRY_LOCK or filename.startswith("."):
                    continue
                if _MARKER_FILENAME.fullmatch(filename) is None:
                    raise WorkspaceOwnershipError(
                        "Workspace ownership registry contains an invalid entry",
                    )
                yield filename
    except WorkspaceOwnershipError:
        raise
    except OSError as exc:
        raise WorkspaceOwnershipError(
            "Workspace ownership registry could not be read",
        ) from exc


def _validate_marker(marker: WorkspaceOwnershipMarker) -> None:
    if marker.schema_version != 1:
        raise WorkspaceOwnershipError("Workspace ownership schema is unsupported")
    _validate_identifier(marker.job_id, label="job")
    _validate_identifier(marker.user_id, label="account")
    if type(marker.created_at) is not int or marker.created_at <= 0:
        raise WorkspaceOwnershipError("Workspace ownership timestamp is invalid")


def _validate_identifier(value: object, *, label: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise WorkspaceOwnershipError(f"Workspace ownership {label} identifier is invalid")


def _marker_filename(job_id: str) -> str:
    return f"{hashlib.sha256(job_id.encode('utf-8')).hexdigest()}{_MARKER_SUFFIX}"


def _write_all(file_descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(file_descriptor, payload[offset:])
        if written <= 0:
            raise OSError("workspace ownership write made no progress")
        offset += written
