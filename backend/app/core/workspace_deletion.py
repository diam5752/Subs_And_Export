"""Exact, local-only deletion primitives for per-job media workspaces."""

from __future__ import annotations

import shutil
from pathlib import Path

UPLOAD_SUFFIXES = frozenset({".mp4", ".mov", ".mkv"})


def delete_job_workspace(
    *,
    job_id: str,
    uploads_dir: Path,
    artifacts_dir: Path,
) -> None:
    """Delete the exact local upload and artifact tree for one job."""
    artifacts_root = artifacts_dir.resolve()
    artifact_dir = artifacts_root / job_id
    if artifact_dir.is_symlink():
        # Never follow a workspace symlink into another job. The link belongs
        # to this exact workspace; its target does not.
        delete_local_path(artifact_dir)
    else:
        resolved_artifact_dir = artifact_dir.resolve()
        if resolved_artifact_dir.parent != artifacts_root:
            raise ValueError("Invalid job workspace path")
        if artifact_dir.exists():
            delete_local_path(artifact_dir)

    if not uploads_dir.exists():
        return
    expected_stem = f"{job_id}_input"
    for item in uploads_dir.iterdir():
        if item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES:
            delete_local_path(item)


def delete_local_path(path: Path) -> None:
    """Delete one exact local path without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
