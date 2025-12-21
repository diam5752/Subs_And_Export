from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.database import Database


def test_database_rejects_sqlite_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GSP_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")

    with pytest.raises(RuntimeError):
        Database(str(tmp_path / "app.db"))


def test_database_requires_postgres_url(monkeypatch, tmp_path: Path) -> None:
    from backend.app.core.config import settings
    
    monkeypatch.delenv("GSP_DATABASE_URL", raising=False)
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))
    # Also patch settings since the value is cached at import time
    monkeypatch.setattr(settings, "database_url", None)

    with pytest.raises(RuntimeError):
        Database()
