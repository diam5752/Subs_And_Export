from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.workspace_deletion import delete_job_workspace
from backend.app.core.workspace_ownership import (
    get_workspace_owner,
    record_workspace_ownership,
)


def test_delete_job_workspace_removes_all_local_media_and_transcription(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    job_id = "private-job"

    owned_uploads = [
        uploads_dir / f"{job_id}_input.mp4",
        uploads_dir / f"{job_id}_input.mov",
        uploads_dir / f"{job_id}_input.mkv",
    ]
    for upload in owned_uploads:
        upload.write_bytes(b"private source")

    artifact_dir = artifacts_dir / job_id
    nested_export_dir = artifact_dir / "exports"
    nested_export_dir.mkdir(parents=True)
    transcription_path = artifact_dir / "transcription.json"
    transcription_path.write_text(
        '[{"start": 0, "end": 1, "text": "private transcript"}]',
        encoding="utf-8",
    )
    (artifact_dir / "processed.mp4").write_bytes(b"private result")
    (nested_export_dir / "subtitles.srt").write_text("private subtitle", encoding="utf-8")

    unrelated_upload = uploads_dir / "other-job_input.mp4"
    unrelated_artifact = artifacts_dir / "other-job" / "transcription.json"
    unrelated_upload.write_bytes(b"keep")
    unrelated_artifact.parent.mkdir()
    unrelated_artifact.write_text("[]", encoding="utf-8")
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=job_id,
        user_id="private-user",
    )
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id="other-job",
        user_id="other-user",
    )

    # REGRESSION: every accepted local upload variant and the complete artifact
    # tree, including transcription data and nested exports, belongs to the job
    # workspace and must disappear together.
    delete_job_workspace(
        job_id=job_id,
        uploads_dir=uploads_dir,
        artifacts_dir=artifacts_dir,
        expected_user_id="private-user",
    )

    assert all(not upload.exists() for upload in owned_uploads)
    assert not artifact_dir.exists()
    assert get_workspace_owner(data_dir=tmp_path, job_id=job_id) is None
    assert unrelated_upload.is_file()
    assert unrelated_artifact.is_file()
    assert get_workspace_owner(data_dir=tmp_path, job_id="other-job") == "other-user"


def test_delete_job_workspace_rejects_paths_outside_artifact_root(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    outside_transcript = tmp_path / "outside" / "transcription.json"
    outside_transcript.parent.mkdir()
    outside_transcript.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid job workspace path"):
        delete_job_workspace(
            job_id="../outside",
            uploads_dir=uploads_dir,
            artifacts_dir=artifacts_dir,
        )

    assert outside_transcript.is_file()


def test_delete_job_workspace_unlinks_artifact_symlink_without_deleting_target(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    other_workspace = artifacts_dir / "other-job"
    other_workspace.mkdir()
    other_transcript = other_workspace / "transcription.json"
    other_transcript.write_text("private other user transcript", encoding="utf-8")
    owned_link = artifacts_dir / "owned-job"
    owned_link.symlink_to(other_workspace, target_is_directory=True)

    delete_job_workspace(
        job_id="owned-job",
        uploads_dir=uploads_dir,
        artifacts_dir=artifacts_dir,
    )

    assert not owned_link.exists()
    assert not owned_link.is_symlink()
    assert other_transcript.read_text(encoding="utf-8") == "private other user transcript"
