"""SQLite-backed persistence utilities for users, sessions, and history."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import config


@dataclass(slots=True)
class DatabaseSettings:
    """Simple settings object for database initialization."""

    path: Path
    busy_timeout_ms: int = 5000
    enable_wal: bool = True


class Database:
    """Lightweight SQLite wrapper with schema management."""

    def __init__(self, path: str | Path | None = None) -> None:
        env_path = os.getenv("GSP_DATABASE_PATH")
        db_path = Path(path or env_path or (config.PROJECT_ROOT / "logs" / "app.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = DatabaseSettings(path=db_path)
        self._initialized = False
        self._lock = threading.Lock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            str(self.settings.path),
            check_same_thread=False,
            isolation_level=None,  # autocommit for WAL friendliness
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {self.settings.busy_timeout_ms}")
        if self.settings.enable_wal:
            conn.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            if not self._initialized:
                self._ensure_schema(conn)
                self._initialized = True
        try:
            yield conn
        finally:
            conn.close()

    # Schema helpers
    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                password_hash TEXT,
                google_sub TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                user_agent TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                data TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_history_user_ts ON history(user_id, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub);

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL, -- pending, processing, completed, failed
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                progress INTEGER DEFAULT 0,
                message TEXT,
                result_data TEXT, -- JSON blob for output paths etc.
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                user_id TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                user_agent TEXT,
                ip TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);
            CREATE INDEX IF NOT EXISTS idx_oauth_states_provider ON oauth_states(provider);

            CREATE TABLE IF NOT EXISTS gcs_uploads (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                object_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_gcs_uploads_user ON gcs_uploads(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gcs_uploads_expires ON gcs_uploads(expires_at);
            """
        )

    # JSON helpers for adapters
    @staticmethod
    def dumps(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def loads(data: str) -> dict:
        try:
            return json.loads(data)
        except Exception:
            return {}
