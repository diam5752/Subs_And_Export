"""GCS upload session persistence (anti-replay / ownership binding)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from .database import Database

DEFAULT_GCS_UPLOAD_TTL_SECONDS = 60 * 60  # 1 hour


@dataclass(frozen=True, slots=True)
class GcsUploadSession:
    id: str
    user_id: str
    object_name: str
    content_type: str
    original_filename: str
    created_at: int
    expires_at: int
    used_at: int | None


class GcsUploadStore:
    """SQLite-backed store for short-lived GCS upload sessions."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def issue_upload(
        self,
        *,
        user_id: str,
        object_name: str,
        content_type: str,
        original_filename: str,
        ttl_seconds: int = DEFAULT_GCS_UPLOAD_TTL_SECONDS,
    ) -> GcsUploadSession:
        upload_id = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + max(60, ttl_seconds)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO gcs_uploads(
                    id, user_id, object_name, content_type, original_filename, created_at, expires_at, used_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (upload_id, user_id, object_name, content_type, original_filename, now, expires_at),
            )
            conn.execute("DELETE FROM gcs_uploads WHERE expires_at <= ?", (now,))
        return GcsUploadSession(
            id=upload_id,
            user_id=user_id,
            object_name=object_name,
            content_type=content_type,
            original_filename=original_filename,
            created_at=now,
            expires_at=expires_at,
            used_at=None,
        )

    def consume_upload(self, *, upload_id: str, user_id: str) -> GcsUploadSession | None:
        now = int(time.time())
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, object_name, content_type, original_filename, created_at, expires_at, used_at
                FROM gcs_uploads
                WHERE id = ?
                """,
                (upload_id,),
            ).fetchone()
            if not row:
                return None

            if int(row["expires_at"]) <= now:
                conn.execute("DELETE FROM gcs_uploads WHERE id = ?", (upload_id,))
                return None

            if str(row["user_id"]) != user_id:
                return None

            if row["used_at"] is not None:
                return None

            conn.execute("UPDATE gcs_uploads SET used_at = ? WHERE id = ?", (now, upload_id))
            conn.execute("DELETE FROM gcs_uploads WHERE expires_at <= ?", (now,))

            return GcsUploadSession(
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                object_name=str(row["object_name"]),
                content_type=str(row["content_type"]),
                original_filename=str(row["original_filename"]),
                created_at=int(row["created_at"]),
                expires_at=int(row["expires_at"]),
                used_at=now,
            )

