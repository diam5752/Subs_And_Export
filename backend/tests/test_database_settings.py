from __future__ import annotations

from pathlib import Path

from backend.app.core.database import Database


def test_database_path_overrides_env_url(monkeypatch, tmp_path: Path) -> None:
    # REGRESSION: pytest loads `.env` with a Postgres `GSP_DATABASE_URL`, but unit tests passing
    # a sqlite path must never require Postgres drivers.
    monkeypatch.setenv("GSP_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")

    db = Database(tmp_path / "app.db")

    assert db.settings.url.startswith("sqlite")


def test_database_env_path_overrides_env_url(monkeypatch, tmp_path: Path) -> None:
    # REGRESSION: test harness sets `GSP_DATABASE_PATH`; it must override `.env` Postgres config.
    monkeypatch.setenv("GSP_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))

    db = Database()

    assert db.settings.url.startswith("sqlite")
