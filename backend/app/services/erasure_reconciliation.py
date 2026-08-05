"""Idempotent replay of durable privacy erasure intents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, select

from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import (
    ErasureJournal,
    ErasureTombstone,
    OrphanWorkspaceErasureTombstone,
    ProviderTranscriptErasureTombstone,
)
from backend.app.core.workspace_deletion import delete_job_workspace
from backend.app.db.models import DbHistoryEvent, DbJob
from backend.app.services.account_erasure import (
    ErasureReplayConflictError,
    erase_account_and_media,
)
from backend.app.services.billing import BillingService
from backend.app.services.points import PointsStore


@dataclass(frozen=True, slots=True)
class ErasureReconciliationReport:
    replayed_events: int
    workspace_events: int
    job_events: int
    account_events: int
    orphan_workspace_events: int
    provider_transcript_events: int
    pruned_events: int


def reconcile_erasure_journal(
    *,
    db: Database,
    data_dir: Path,
    journal: ErasureJournal,
    now: int | None = None,
    provider_transcript_deleter: Callable[[str], None] | None = None,
) -> ErasureReconciliationReport:
    """Replay every tombstone and prune only after the full pass succeeds."""
    entries = journal.read_all()
    billing_service = BillingService(
        db=db,
        points_store=PointsStore(db=db),
    )
    user_store = UserStore(db=db)
    workspace_events = 0
    job_events = 0
    account_events = 0
    orphan_workspace_events = 0
    provider_transcript_events = 0

    for entry in entries:
        if isinstance(entry, ProviderTranscriptErasureTombstone):
            _replay_provider_transcript_erasure(
                tombstone=entry,
                provider_transcript_deleter=provider_transcript_deleter,
            )
            provider_transcript_events += 1
        elif isinstance(entry, OrphanWorkspaceErasureTombstone):
            _replay_orphan_workspace_erasure(
                data_dir=data_dir,
                tombstone=entry,
            )
            orphan_workspace_events += 1
        elif entry.kind == "workspace":
            _replay_workspace_erasure(
                db=db,
                data_dir=data_dir,
                tombstone=entry,
                delete_database_jobs=False,
            )
            workspace_events += 1
        elif entry.kind == "job":
            _replay_workspace_erasure(
                db=db,
                data_dir=data_dir,
                tombstone=entry,
                delete_database_jobs=True,
            )
            job_events += 1
        else:
            erase_account_and_media(
                db=db,
                billing_service=billing_service,
                user_store=user_store,
                user_id=entry.user_id,
                data_dir=data_dir,
                journal=None,
                expected_job_ids=entry.job_ids,
                require_terminal_jobs=False,
            )
            account_events += 1

    pruned_events = journal.prune_expired(now=now)
    return ErasureReconciliationReport(
        replayed_events=len(entries),
        workspace_events=workspace_events,
        job_events=job_events,
        account_events=account_events,
        orphan_workspace_events=orphan_workspace_events,
        provider_transcript_events=provider_transcript_events,
        pruned_events=pruned_events,
    )


def _replay_provider_transcript_erasure(
    *,
    tombstone: ProviderTranscriptErasureTombstone,
    provider_transcript_deleter: Callable[[str], None] | None,
) -> None:
    if tombstone.provider != "elevenlabs":
        raise ErasureReplayConflictError("Erasure intent names an unsupported provider")
    if provider_transcript_deleter is not None:
        provider_transcript_deleter(tombstone.transcript_id)
        return

    # Import lazily so local-only installations can inspect and replay local
    # tombstones without initializing provider clients or credentials.
    from backend.app.services.transcription.elevenlabs_scribe import (
        delete_elevenlabs_transcript,
    )

    delete_elevenlabs_transcript(tombstone.transcript_id)


def _replay_orphan_workspace_erasure(
    *,
    data_dir: Path,
    tombstone: OrphanWorkspaceErasureTombstone,
) -> None:
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    for job_id in tombstone.job_ids:
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=uploads_dir,
            artifacts_dir=artifacts_dir,
        )


def _replay_workspace_erasure(
    *,
    db: Database,
    data_dir: Path,
    tombstone: ErasureTombstone,
    delete_database_jobs: bool,
) -> None:
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    with db.session() as session:
        restored_jobs = list(
            session.scalars(
                select(DbJob).where(DbJob.id.in_(tombstone.job_ids)).with_for_update(),
            ).all(),
        )
        if any(job.user_id != tombstone.user_id for job in restored_jobs):
            raise ErasureReplayConflictError("Restored project ownership conflicts with erasure intent")

        for job_id in tombstone.job_ids:
            delete_job_workspace(
                job_id=job_id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_dir,
            )

        if not delete_database_jobs:
            return

        target_ids = set(tombstone.job_ids)
        history_rows = session.execute(
            select(DbHistoryEvent.id, DbHistoryEvent.data).where(
                DbHistoryEvent.user_id == tombstone.user_id,
            ),
        ).all()
        history_ids = [
            int(event_id)
            for event_id, data in history_rows
            if isinstance(data, dict) and data.get("job_id") in target_ids
        ]
        if history_ids:
            session.execute(
                delete(DbHistoryEvent).where(DbHistoryEvent.id.in_(history_ids)),
            )
        session.execute(
            delete(DbJob).where(
                DbJob.id.in_(tombstone.job_ids),
                DbJob.user_id == tombstone.user_id,
            ),
        )
