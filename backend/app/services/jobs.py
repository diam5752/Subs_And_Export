import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..core.database import Database


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
            result_data=None
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(id, user_id, status, created_at, updated_at, progress, message)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (job.id, job.user_id, job.status, job.created_at, job.updated_at, job.progress, job.message)
            )
        return job

    def update_job(self, job_id: str, status: str | None = None, progress: int | None = None, message: str | None = None, result_data: Dict | None = None):
        updates = []
        params = []
        if status:
            updates.append("status = ?")
            params.append(status)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if message is not None:
            updates.append("message = ?")
            params.append(message)
        if result_data is not None:
            updates.append("result_data = ?")
            params.append(self.db.dumps(result_data))

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(int(time.time()))

        params.append(job_id)

        query = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"  # nosec: updates are hardcoded
        with self.db.connect() as conn:
            conn.execute(query, tuple(params))

    def get_job(self, job_id: str) -> Optional[Job]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return Job(
            id=row["id"],
            user_id=row["user_id"],
            status=row["status"],
            progress=row["progress"],
            message=row["message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result_data=self.db.loads(row["result_data"]) if row["result_data"] else None
        )

    def list_jobs_for_user(self, user_id: str, limit: int = 10) -> List[Job]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [
            Job(
                id=row["id"],
                user_id=row["user_id"],
                status=row["status"],
                progress=row["progress"],
                message=row["message"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                result_data=self.db.loads(row["result_data"]) if row["result_data"] else None
            )
            for row in rows
        ]

    def delete_job(self, job_id: str) -> None:
        """Delete a job from the database."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def delete_jobs_for_user(self, user_id: str) -> None:
        """Delete all jobs for a user (for account deletion)."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE user_id = ?", (user_id,))

    def count_jobs_for_user(self, user_id: str) -> int:
        """Count total jobs for a user (for pagination)."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM jobs WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        return row["count"] if row else 0

    def list_jobs_for_user_paginated(
        self, user_id: str, offset: int = 0, limit: int = 10
    ) -> List[Job]:
        """List jobs for a user with pagination support."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM jobs WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset)
            ).fetchall()
        return [
            Job(
                id=row["id"],
                user_id=row["user_id"],
                status=row["status"],
                progress=row["progress"],
                message=row["message"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                result_data=self.db.loads(row["result_data"]) if row["result_data"] else None
            )
            for row in rows
        ]

    def delete_jobs(self, job_ids: List[str], user_id: str) -> int:
        """Delete multiple jobs by IDs (with ownership check). Returns count deleted."""
        if not job_ids:
            return 0
        placeholders = ",".join("?" * len(job_ids))
        with self.db.connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders}) AND user_id = ?",  # nosec: placeholders generated safely
                (*job_ids, user_id)
            )
            return cursor.rowcount

    def list_jobs_created_before(self, timestamp: int) -> List[Job]:
        """List jobs created before a certain timestamp (for retention)."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE created_at < ?",
                (timestamp,)
            ).fetchall()
        return [
            Job(
                id=row["id"],
                user_id=row["user_id"],
                status=row["status"],
                progress=row["progress"],
                message=row["message"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                result_data=self.db.loads(row["result_data"]) if row["result_data"] else None
            )
            for row in rows
        ]
