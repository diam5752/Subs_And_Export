from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from backend.app.core import auth
from backend.app.core.auth import SessionStore
from backend.app.core.database import Database


class FakeDatabase:
    def __init__(self, scalar_result: int | None) -> None:
        self.session_mock = MagicMock(spec=Session)
        self.session_mock.scalar.return_value = scalar_result
        self.session_calls = 0

    @contextmanager
    def session(self) -> Iterator[Session]:
        self.session_calls += 1
        yield self.session_mock


def _session_store(db: FakeDatabase) -> SessionStore:
    return SessionStore(db=cast(Database, db))


def test_valid_session_created_at_rejects_empty_token_without_querying() -> None:
    db = FakeDatabase(scalar_result=1_800_000_000)

    assert _session_store(db).get_valid_session_created_at("") is None
    assert db.session_calls == 0


def test_valid_session_created_at_hashes_token_and_requires_future_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_800_000_000
    bearer_token = "opaque-bearer-token"
    db = FakeDatabase(scalar_result=now - 60)
    monkeypatch.setattr("backend.app.core.auth.time.time", lambda: now)

    created_at = _session_store(db).get_valid_session_created_at(bearer_token)

    assert created_at == now - 60
    statement = db.session_mock.scalar.call_args.args[0]
    compiled = statement.compile()
    bound_values = set(compiled.params.values())
    assert bearer_token not in bound_values
    assert auth._hash_token(bearer_token) in bound_values
    assert now in bound_values
    assert "sessions.expires_at >" in str(statement)


def test_valid_session_created_at_returns_none_for_invalid_or_expired_token() -> None:
    db = FakeDatabase(scalar_result=None)

    assert _session_store(db).get_valid_session_created_at("invalid-or-expired") is None
