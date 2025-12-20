"""SQLAlchemy-backed persistence utilities (PostgreSQL only)."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..db import models as _models  # noqa: F401  # ensure models are registered
from ..db.base import Base
from . import config, logging


logger = logging.setup_logging()


@dataclass(slots=True, frozen=True)
class DatabaseSettings:
    url: str


class Database:
    """SQLAlchemy wrapper for PostgreSQL connections."""

    def __init__(self, url: str | None = None) -> None:
        env_url = os.getenv("GSP_DATABASE_URL")

        if url:
            resolved_url = url
        elif env_url:
            resolved_url = env_url
        else:
            raise RuntimeError(
                "GSP_DATABASE_URL environment variable is required. "
                "Set it to your PostgreSQL connection string, e.g.: "
                "postgresql+psycopg://user:pass@localhost:5432/dbname"
            )

        if not resolved_url.startswith("postgresql"):
            raise RuntimeError(
                f"Only PostgreSQL is supported. Got: {resolved_url.split('://')[0]}. "
                "Please set GSP_DATABASE_URL to a PostgreSQL connection string."
            )

        self.settings = DatabaseSettings(url=resolved_url)
        logger.info("💾 Database: Initializing PostgreSQL connection", extra={"data": {"url_prefix": resolved_url.split("://")[0]}})

        self._engine = create_engine(resolved_url, pool_pre_ping=True)
        self._sessionmaker = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

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
