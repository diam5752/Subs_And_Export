"""Focused application lifespan regression tests."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from backend import main
from backend.app.core.config import settings


def test_lifespan_disposes_database_when_startup_reconciliation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: reconciliation ran before the lifespan cleanup scope, leaking
    # the SQLAlchemy engine whenever startup reconciliation raised.
    disposed = False

    class FailingStartupDatabase:
        def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    def fail_reconciliation(_database: FailingStartupDatabase) -> int:
        raise RuntimeError("startup reconciliation failed")

    monkeypatch.setattr(main, "assert_runtime_billing_configuration", lambda: None)
    monkeypatch.setattr(main, "assert_runtime_privacy_configuration", lambda: None)
    monkeypatch.setattr(main, "reclaim_abandoned_lifecycle_locks", lambda **_kwargs: 0)
    monkeypatch.setattr(main, "Database", FailingStartupDatabase)
    monkeypatch.setattr(main, "reconcile_stranded_cancellations", fail_reconciliation)
    monkeypatch.setattr(settings, "retention_cleanup_enabled", False)

    async def start_application() -> None:
        async with main.lifespan(FastAPI()):
            pytest.fail("The application must not start after reconciliation fails")

    with pytest.raises(RuntimeError, match="startup reconciliation failed"):
        asyncio.run(start_application())

    assert disposed is True
