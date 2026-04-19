from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.core.oauth_state import OAuthStateStore
from backend.app.db.models import DbOAuthState


class FakeDb:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    @contextmanager
    def session(self):
        yield self._session


def test_issue_state_persists_and_enforces_minimum_ttl(monkeypatch) -> None:
    session = MagicMock()
    store = OAuthStateStore(db=FakeDb(session))

    monkeypatch.setattr("backend.app.core.oauth_state.secrets.token_urlsafe", lambda _n: "state-123")
    monkeypatch.setattr("backend.app.core.oauth_state.time.time", lambda: 100)

    issued = store.issue_state(
        provider="google",
        user_id="user-1",
        user_agent="browser",
        ip="127.0.0.1",
        ttl_seconds=5,
    )

    assert issued == "state-123"
    added = session.add.call_args.args[0]
    assert isinstance(added, DbOAuthState)
    assert added.state == "state-123"
    assert added.provider == "google"
    assert added.user_id == "user-1"
    assert added.user_agent == "browser"
    assert added.ip == "127.0.0.1"
    assert added.created_at == 100
    assert added.expires_at == 130
    session.execute.assert_called_once()


def test_consume_state_returns_false_when_missing() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    store = OAuthStateStore(db=FakeDb(session))

    assert store.consume_state(
        provider="google",
        state="missing",
        user_id=None,
        user_agent=None,
        ip=None,
    ) is False


def test_consume_state_deletes_expired_rows(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.core.oauth_state.time.time", lambda: 100)
    session = MagicMock()
    session.scalar.return_value = SimpleNamespace(
        state="expired",
        provider="google",
        user_id=None,
        expires_at=99,
        user_agent=None,
        ip=None,
    )
    store = OAuthStateStore(db=FakeDb(session))

    assert store.consume_state(
        provider="google",
        state="expired",
        user_id=None,
        user_agent=None,
        ip=None,
    ) is False
    session.execute.assert_called_once()


def test_consume_state_rejects_provider_user_agent_and_ip_mismatches(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.core.oauth_state.time.time", lambda: 100)

    for row, provider, user_id, user_agent, ip in [
        (
            SimpleNamespace(
                state="s1",
                provider="google",
                user_id=None,
                expires_at=130,
                user_agent=None,
                ip=None,
            ),
            "local",
            None,
            None,
            None,
        ),
        (
            SimpleNamespace(
                state="s2",
                provider="google",
                user_id="user-1",
                expires_at=130,
                user_agent=None,
                ip=None,
            ),
            "google",
            "user-2",
            None,
            None,
        ),
        (
            SimpleNamespace(
                state="s3",
                provider="google",
                user_id=None,
                expires_at=130,
                user_agent="expected-agent",
                ip=None,
            ),
            "google",
            None,
            "other-agent",
            None,
        ),
        (
            SimpleNamespace(
                state="s4",
                provider="google",
                user_id=None,
                expires_at=130,
                user_agent=None,
                ip="1.1.1.1",
            ),
            "google",
            None,
            None,
            "2.2.2.2",
        ),
    ]:
        session = MagicMock()
        session.scalar.return_value = row
        store = OAuthStateStore(db=FakeDb(session))
        assert store.consume_state(
            provider=provider,
            state=row.state,
            user_id=user_id,
            user_agent=user_agent,
            ip=ip,
        ) is False


def test_consume_state_deletes_and_returns_true_on_success(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.core.oauth_state.time.time", lambda: 100)
    session = MagicMock()
    session.scalar.return_value = SimpleNamespace(
        state="ok",
        provider="google",
        user_id="user-1",
        expires_at=130,
        user_agent="browser",
        ip="127.0.0.1",
    )
    store = OAuthStateStore(db=FakeDb(session))

    assert store.consume_state(
        provider="google",
        state="ok",
        user_id="user-1",
        user_agent="browser",
        ip="127.0.0.1",
    ) is True
    session.execute.assert_called_once()
