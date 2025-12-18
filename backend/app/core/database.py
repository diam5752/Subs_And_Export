"""SQLAlchemy-backed persistence utilities (SQLite for tests, Postgres for production)."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..db import models as _models  # noqa: F401  # ensure models are registered
from ..db.base import Base
from . import config


@dataclass(slots=True, frozen=True)
class DatabaseSettings:
    url: str


class Database:
    """Small SQLAlchemy wrapper with safe defaults and sqlite pragmas for tests."""

    def __init__(self, path: str | Path | None = None, url: str | None = None) -> None:
        env_url = os.getenv("GSP_DATABASE_URL")
        env_path = os.getenv("GSP_DATABASE_PATH")

        if url:
            resolved_url = url
        elif path is not None:
            candidate_path = Path(path)
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_url = f"sqlite+pysqlite:///{candidate_path}"
        elif env_path:
            candidate_path = Path(env_path)
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_url = f"sqlite+pysqlite:///{candidate_path}"
        elif env_url:
            resolved_url = env_url
        else:
            candidate_path = Path(config.PROJECT_ROOT / "logs" / "app.db")
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_url = f"sqlite+pysqlite:///{candidate_path}"

        self.settings = DatabaseSettings(url=resolved_url)
        self._engine = self._build_engine(self.settings.url)
        self._sessionmaker = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        # Tests use SQLite; keep local-first behavior by auto-creating tables for sqlite URLs.
        if self.settings.url.startswith("sqlite"):
            Base.metadata.create_all(self._engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self._engine.dispose()

    @staticmethod
    def dumps(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def loads(data: str) -> dict:
        try:
            return json.loads(data)
        except Exception:
            return {}

    def _build_engine(self, url: str) -> Engine:
        if url.startswith("sqlite"):
            engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
            self._configure_sqlite(engine)
            return engine

        return create_engine(url, pool_pre_ping=True)

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
