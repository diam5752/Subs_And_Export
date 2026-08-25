"""Exact, local-only deletion primitives for per-job media workspaces."""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import stat
import time
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .workspace_ownership import (
    WorkspaceOwnershipConflictError,
    get_workspace_owner,
    remove_workspace_ownership_after_verified_cleanup,
)

UPLOAD_SUFFIXES = frozenset({".mp4", ".mov", ".mkv"})
JOB_WORKSPACE_LOCK_TIMEOUT_SECONDS = 30.0
ACCOUNT_LIFECYCLE_LOCK_TIMEOUT_SECONDS = 30.0
_JOB_WORKSPACE_LOCK_POLL_SECONDS = 0.05
_JOB_WORKSPACE_LOCK_DIR = ".job-locks"
_ACCOUNT_LIFECYCLE_LOCK_DIR = ".account-locks"
_LOCK_REGISTRY_FILE = ".registry"
_LOCK_REGISTRY_CLEANUP_TIMEOUT_SECONDS = 1.0
_LOCK_REGISTRY_SCAVENGE_TIMEOUT_SECONDS = 0.05
_LOCK_DIGEST_LENGTH = 64


class JobWorkspaceLockTimeoutError(TimeoutError):
    """Raised when a job workspace remains busy past the bounded wait."""


class AccountLifecycleLockTimeoutError(JobWorkspaceLockTimeoutError):
    """Raised when account creation or erasure cannot cross its barrier."""


def reclaim_abandoned_lifecycle_locks(*, data_dir: Path) -> int:
    """Retire unlocked identity files left by killed worker processes.

    The registry excludes new openers while each candidate is checked. An
    identity file is removed only after its own exclusive lock succeeds, so a
    live shared or exclusive holder is never detached from future contenders.
    Unknown directory entries are preserved for fail-closed manual review.
    """
    reclaimed = 0
    for lock_dir_name in (
        _JOB_WORKSPACE_LOCK_DIR,
        _ACCOUNT_LIFECYCLE_LOCK_DIR,
    ):
        lock_root = data_dir.resolve() / lock_dir_name
        if not lock_root.exists():
            continue

        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        directory_fd = os.open(lock_root, directory_flags)
        registry_fd: int | None = None
        try:
            os.fchmod(directory_fd, 0o700)
            registry_fd = _open_private_regular_file(
                directory_fd=directory_fd,
                name=_LOCK_REGISTRY_FILE,
                invalid_message="Lock registry is not a regular file",
            )
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    lock_name = entry.name
                    if not _is_generated_lock_name(lock_name):
                        continue
                    registry_acquired = _acquire_registry_for_cleanup(
                        registry_fd,
                        timeout_seconds=_LOCK_REGISTRY_SCAVENGE_TIMEOUT_SECONDS,
                    )
                    if not registry_acquired:
                        # Normal request admission takes priority. A later
                        # startup or retention pass will retry the namespace.
                        break
                    lock_fd: int | None = None
                    lock_acquired = False
                    try:
                        lock_fd = os.open(
                            lock_name,
                            os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                            dir_fd=directory_fd,
                        )
                        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                            continue
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            lock_acquired = True
                        except BlockingIOError:
                            continue
                        if _unlink_lock_if_same(
                            directory_fd=directory_fd,
                            lock_fd=lock_fd,
                            lock_name=lock_name,
                        ):
                            reclaimed += 1
                    except OSError:
                        # A symlink, concurrent disappearance, or invalid path
                        # is never followed or removed by the scavenger.
                        continue
                    finally:
                        if lock_fd is not None:
                            if lock_acquired:
                                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            os.close(lock_fd)
                        fcntl.flock(registry_fd, fcntl.LOCK_UN)
        finally:
            if registry_fd is not None:
                os.close(registry_fd)
            os.close(directory_fd)
    return reclaimed


def _is_generated_lock_name(lock_name: str) -> bool:
    if not lock_name.endswith(".lock"):
        return False
    digest = lock_name.removesuffix(".lock")
    return len(digest) == _LOCK_DIGEST_LENGTH and all(
        character in "0123456789abcdef" for character in digest
    )


@contextmanager
def lock_account_lifecycle(
    *,
    data_dir: Path,
    user_id: str,
    shared: bool,
    timeout_seconds: float = ACCOUNT_LIFECYCLE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize account erasure against pre-row media creation.

    Uploads and reprocessing hold a shared lock, so normal same-account
    concurrency remains available. Account erasure holds the exclusive form
    before discovering jobs and through deleting the user row. Callers must
    always take this account lock before any per-job workspace lock.
    """
    with _lock_identity(
        data_dir=data_dir,
        lock_dir_name=_ACCOUNT_LIFECYCLE_LOCK_DIR,
        lock_name=_account_lifecycle_lock_name(user_id),
        shared=shared,
        timeout_seconds=timeout_seconds,
        timeout_error=AccountLifecycleLockTimeoutError,
        timeout_message="Account media is busy. Please retry shortly.",
        invalid_lock_message="Account lifecycle lock is not a regular file",
    ):
        yield


@contextmanager
def lock_job_workspace(
    *,
    data_dir: Path,
    job_id: str,
    timeout_seconds: float = JOB_WORKSPACE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize one job's writers and erasers across backend processes."""
    with _lock_identity(
        data_dir=data_dir,
        lock_dir_name=_JOB_WORKSPACE_LOCK_DIR,
        lock_name=_job_workspace_lock_name(job_id),
        shared=False,
        timeout_seconds=timeout_seconds,
        timeout_error=JobWorkspaceLockTimeoutError,
        timeout_message="Project is busy. Please retry shortly.",
        invalid_lock_message="Job workspace lock is not a regular file",
    ):
        yield


@contextmanager
def _lock_identity(
    *,
    data_dir: Path,
    lock_dir_name: str,
    lock_name: str,
    shared: bool,
    timeout_seconds: float,
    timeout_error: type[JobWorkspaceLockTimeoutError],
    timeout_message: str,
    invalid_lock_message: str,
) -> Iterator[None]:
    """Lock one opaque identity without persistent per-identity inode growth.

    A short registry lock serializes opening and retiring identity files. Busy
    contenders never retain an open descriptor, so the last holder can unlink
    its file without splitting future callers across different inodes.
    """
    if timeout_seconds < 0:
        label = (
            "Account lifecycle"
            if lock_dir_name == _ACCOUNT_LIFECYCLE_LOCK_DIR
            else "Job workspace"
        )
        raise ValueError(f"{label} lock timeout cannot be negative")

    lock_root = data_dir.resolve() / lock_dir_name
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_fd = os.open(lock_root, directory_flags)
    registry_fd: int | None = None
    lock_fd: int | None = None
    acquired = False
    registry_acquired = False
    deadline = time.monotonic() + timeout_seconds
    lock_mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    last_busy_error: BlockingIOError | None = None
    try:
        os.fchmod(directory_fd, 0o700)
        registry_fd = _open_private_regular_file(
            directory_fd=directory_fd,
            name=_LOCK_REGISTRY_FILE,
            invalid_message="Lock registry is not a regular file",
        )

        while not acquired:
            try:
                fcntl.flock(registry_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                registry_acquired = True
            except BlockingIOError as exc:
                last_busy_error = exc
            else:
                candidate_fd: int | None = None
                try:
                    candidate_fd = _open_private_regular_file(
                        directory_fd=directory_fd,
                        name=lock_name,
                        invalid_message=invalid_lock_message,
                    )
                    try:
                        fcntl.flock(candidate_fd, lock_mode | fcntl.LOCK_NB)
                    except BlockingIOError as exc:
                        last_busy_error = exc
                    else:
                        lock_fd = candidate_fd
                        candidate_fd = None
                        acquired = True
                finally:
                    if candidate_fd is not None:
                        os.close(candidate_fd)
                    fcntl.flock(registry_fd, fcntl.LOCK_UN)
                    registry_acquired = False

            if acquired:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise timeout_error(timeout_message) from last_busy_error
            time.sleep(min(_JOB_WORKSPACE_LOCK_POLL_SECONDS, remaining))

        yield
    finally:
        if registry_acquired and registry_fd is not None:
            fcntl.flock(registry_fd, fcntl.LOCK_UN)
        if lock_fd is not None:
            if acquired:
                registry_acquired = _acquire_registry_for_cleanup(registry_fd)
                try:
                    if registry_acquired:
                        if shared:
                            # Stop contributing a shared holder while the
                            # registry prevents any new opener. Only the last
                            # shared holder can promote and retire the inode.
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            acquired = False
                            try:
                                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                acquired = True
                            except BlockingIOError:
                                pass
                        if acquired:
                            _unlink_lock_if_same(
                                directory_fd=directory_fd,
                                lock_fd=lock_fd,
                                lock_name=lock_name,
                            )
                finally:
                    if acquired:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    if registry_acquired and registry_fd is not None:
                        fcntl.flock(registry_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        if registry_fd is not None:
            os.close(registry_fd)
        os.close(directory_fd)


def _open_private_regular_file(
    *,
    directory_fd: int,
    name: str,
    invalid_message: str,
) -> int:
    file_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    file_fd: int | None = None
    for attempt in range(3):
        try:
            file_fd = os.open(
                name,
                file_flags,
                0o600,
                dir_fd=directory_fd,
            )
            break
        except FileNotFoundError:
            # Darwin can transiently report ENOENT when several first-time
            # callers materialize the same O_CREAT registry inode. The open
            # directory descriptor remains the trusted boundary, so retrying
            # the exact relative name is safe and keeps parallel admission
            # from turning into a 500 response.
            if attempt == 2:
                raise
            time.sleep(0)
    if file_fd is None:
        raise RuntimeError("Private lock file could not be opened")
    try:
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(invalid_message)
        os.fchmod(file_fd, 0o600)
        return file_fd
    except BaseException:
        os.close(file_fd)
        raise


def _acquire_registry_for_cleanup(
    registry_fd: int | None,
    *,
    timeout_seconds: float = _LOCK_REGISTRY_CLEANUP_TIMEOUT_SECONDS,
) -> bool:
    if registry_fd is None:
        return False
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(registry_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_JOB_WORKSPACE_LOCK_POLL_SECONDS, remaining))


def _unlink_lock_if_same(
    *,
    directory_fd: int,
    lock_fd: int,
    lock_name: str,
) -> bool:
    """Retire only the path still naming this exact locked inode."""
    try:
        path_stat = os.stat(lock_name, dir_fd=directory_fd, follow_symlinks=False)
        lock_stat = os.fstat(lock_fd)
        if (
            stat.S_ISREG(path_stat.st_mode)
            and path_stat.st_dev == lock_stat.st_dev
            and path_stat.st_ino == lock_stat.st_ino
        ):
            os.unlink(lock_name, dir_fd=directory_fd)
            return True
    except OSError:
        pass
    return False


@contextmanager
def lock_job_workspaces(
    *,
    data_dir: Path,
    job_ids: Iterable[str],
    timeout_seconds: float = JOB_WORKSPACE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire deduplicated per-job locks in deterministic order and one bound."""
    if timeout_seconds < 0:
        raise ValueError("Job workspace lock timeout cannot be negative")
    representative_by_lock_name: dict[str, str] = {}
    for job_id in sorted(set(job_ids)):
        representative_by_lock_name.setdefault(
            _job_workspace_lock_name(job_id),
            job_id,
        )
    deadline = time.monotonic() + timeout_seconds
    with ExitStack() as stack:
        for lock_name in sorted(representative_by_lock_name):
            remaining = max(0.0, deadline - time.monotonic())
            stack.enter_context(
                lock_job_workspace(
                    data_dir=data_dir,
                    job_id=representative_by_lock_name[lock_name],
                    timeout_seconds=remaining,
                ),
            )
        yield


def _job_workspace_lock_name(job_id: str) -> str:
    if not job_id:
        raise ValueError("Job workspace lock requires a job ID")
    digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
    return f"{digest}.lock"


def _account_lifecycle_lock_name(user_id: str) -> str:
    if not user_id:
        raise ValueError("Account lifecycle lock requires a user ID")
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"{digest}.lock"


def delete_job_workspace(
    *,
    job_id: str,
    uploads_dir: Path,
    artifacts_dir: Path,
    expected_user_id: str | None = None,
) -> None:
    """Delete the exact local upload and artifact tree for one job."""
    artifacts_root = artifacts_dir.resolve()
    artifact_dir = artifacts_root / job_id
    if not artifact_dir.is_symlink():
        resolved_artifact_dir = artifact_dir.resolve()
        if resolved_artifact_dir.parent != artifacts_root:
            raise ValueError("Invalid job workspace path")

    marker_owner = get_workspace_owner(
        data_dir=artifacts_root.parent,
        job_id=job_id,
    )
    if expected_user_id is None:
        if marker_owner is not None:
            raise WorkspaceOwnershipConflictError(
                "Owned workspace cannot be deleted without an expected account",
            )
    elif marker_owner is not None and marker_owner != expected_user_id:
        raise WorkspaceOwnershipConflictError(
            "Workspace ownership does not match the expected account",
        )

    if artifact_dir.is_symlink():
        # Never follow a workspace symlink into another job. The link belongs
        # to this exact workspace; its target does not.
        delete_local_path(artifact_dir)
    else:
        if artifact_dir.exists():
            delete_local_path(artifact_dir)

    expected_stem = f"{job_id}_input"
    if uploads_dir.exists():
        for item in uploads_dir.iterdir():
            if item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES:
                delete_local_path(item)

    artifact_remains = artifact_dir.exists() or artifact_dir.is_symlink()
    upload_remains = uploads_dir.exists() and any(
        item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES
        for item in uploads_dir.iterdir()
    )
    if artifact_remains or upload_remains:
        raise RuntimeError("Job workspace cleanup could not be verified")
    if expected_user_id is not None:
        remove_workspace_ownership_after_verified_cleanup(
            data_dir=artifacts_root.parent,
            job_id=job_id,
            expected_user_id=expected_user_id,
        )


def delete_local_path(path: Path) -> None:
    """Delete one exact local path without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
