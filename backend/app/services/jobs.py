import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import delete, func, select

from ..core.database import Database
from ..db.models import DbJob


@dataclass
class Job:
    id: str
    user_id: str
    status: str
    progress: int
    message: str | None
    created_at: int
    updated_at: int
    result_data: Dict | None

class JobStore:
    def __init__(self, db: Database):
        self.db = db

    def create_job(self, job_id: str, user_id: str) -> Job:
        now = int(time.time())
        job = Job(
            id=job_id,
            user_id=user_id,
            status="pending",
            progress=0,
            message=None,
            created_at=now,
            updated_at=now,
            result_data=None,
        )
        with self.db.session() as session:
            session.add(
                DbJob(
                    id=job.id,
                    user_id=job.user_id,
                    status=job.status,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    progress=job.progress,
                    message=job.message,
                    result_data=job.result_data,
                )
            )
        return job

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result_data: Dict | None = None,
    ) -> None:
        if status is None and progress is None and message is None and result_data is None:
            return

        with self.db.session() as session:
            job = session.get(DbJob, job_id)
            if not job:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if message is not None:
                job.message = message
            if result_data is not None:
                job.result_data = result_data
            job.updated_at = int(time.time())

    def get_job(self, job_id: str) -> Optional[Job]:
        with self.db.session() as session:
            row = session.get(DbJob, job_id)
            if not row:
                return None
            return Job(
                id=row.id,
                user_id=row.user_id,
                status=row.status,
                progress=row.progress,
                message=row.message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                result_data=row.result_data,
            )

    def list_jobs_for_user(self, user_id: str, limit: int = 10) -> List[Job]:
        with self.db.session() as session:
            stmt = (
                select(DbJob)
                .where(DbJob.user_id == user_id)
                .order_by(DbJob.created_at.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt).all())
        return [
            Job(
                id=row.id,
                user_id=row.user_id,
                status=row.status,
                progress=row.progress,
                message=row.message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                result_data=row.result_data,
            )
            for row in rows
        ]

    def get_jobs(self, job_ids: List[str], user_id: str) -> List[Job]:
        """Get multiple jobs by ID for a specific user."""
        if not job_ids:
            return []
        with self.db.session() as session:
            stmt = select(DbJob).where(DbJob.id.in_(job_ids), DbJob.user_id == user_id)
            rows = list(session.scalars(stmt).all())
        return [
            Job(
                id=row.id,
                user_id=row.user_id,
                status=row.status,
                progress=row.progress,
                message=row.message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                result_data=row.result_data,
            )
            for row in rows
        ]

    def delete_job(self, job_id: str) -> None:
        """Delete a job from the database."""
        with self.db.session() as session:
            session.execute(delete(DbJob).where(DbJob.id == job_id))

    def delete_jobs_for_user(self, user_id: str) -> None:
        """Delete all jobs for a user (for account deletion)."""
        with self.db.session() as session:
            session.execute(delete(DbJob).where(DbJob.user_id == user_id))

    def count_jobs_for_user(self, user_id: str) -> int:
        """Count total jobs for a user (for pagination)."""
        with self.db.session() as session:
            count = session.scalar(select(func.count()).select_from(DbJob).where(DbJob.user_id == user_id))
            return int(count or 0)

    def count_active_jobs_for_user(self, user_id: str) -> int:
        """Count active (pending or processing) jobs for a user."""
        with self.db.session() as session:
            count = session.scalar(
                select(func.count())
                .select_from(DbJob)
                .where(DbJob.user_id == user_id, DbJob.status.in_(["pending", "processing"]))
            )
            return int(count or 0)

    def list_jobs_for_user_paginated(
        self, user_id: str, offset: int = 0, limit: int = 10
    ) -> List[Job]:
        """List jobs for a user with pagination support."""
        with self.db.session() as session:
            stmt = (
                select(DbJob)
                .where(DbJob.user_id == user_id)
                .order_by(DbJob.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = list(session.scalars(stmt).all())
        return [
            Job(
                id=row.id,
                user_id=row.user_id,
                status=row.status,
                progress=row.progress,
                message=row.message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                result_data=row.result_data,
            )
            for row in rows
        ]

    def delete_jobs(self, job_ids: List[str], user_id: str) -> int:
        """Delete multiple jobs by IDs (with ownership check). Returns count deleted."""
        if not job_ids:
            return 0
        with self.db.session() as session:
            result = session.execute(delete(DbJob).where(DbJob.id.in_(job_ids), DbJob.user_id == user_id))
            return int(result.rowcount or 0)

    def list_jobs_created_before(self, timestamp: int) -> List[Job]:
        """List jobs created before a certain timestamp (for retention)."""
        with self.db.session() as session:
            stmt = select(DbJob).where(DbJob.created_at < timestamp)
            rows = list(session.scalars(stmt).all())
        return [
            Job(
                id=row.id,
                user_id=row.user_id,
                status=row.status,
                progress=row.progress,
                message=row.message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                result_data=row.result_data,
            )
            for row in rows
        ]
