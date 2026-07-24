from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.app.core import ratelimit


class MockRequest:
    def __init__(self, client_host: str | None = None, headers: dict[str, str] | None = None):
        self.client = SimpleNamespace(host=client_host) if client_host is not None else None
        self.headers = headers or {}


class FakeDb:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    @contextmanager
    def session(self):
        yield self._session


def test_get_client_ip_ignores_invalid_proxy_headers() -> None:
    request = MockRequest(client_host=None, headers={"x-forwarded-for": "nope", "x-real-ip": "also-nope"})
    assert ratelimit.get_client_ip(request) == "unknown"


def test_rate_limiter_can_be_disabled(monkeypatch) -> None:
    limiter = ratelimit.RateLimiter(limit=1, window=60)
    monkeypatch.setenv("GSP_DISABLE_RATELIMIT", "1")
    limiter.check("client-1")
    limiter.check("client-1")


def test_rate_limiter_clears_oversized_client_cache(monkeypatch) -> None:
    limiter = ratelimit.RateLimiter(limit=1, window=60)
    limiter.clients = {f"client-{i}": [0.0] for i in range(10001)}
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)
    monkeypatch.setattr(ratelimit.time, "time", lambda: 10.0)

    limiter.check("fresh-client")

    assert list(limiter.clients) == ["fresh-client"]


def test_authenticated_rate_limiter_clears_oversized_client_cache(monkeypatch) -> None:
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)
    limiter = ratelimit.AuthenticatedRateLimiter(limit=2, window=60)
    limiter.clients = {f"user-{i}": [0.0] for i in range(10001)}
    monkeypatch.setattr(ratelimit.time, "time", lambda: 10.0)

    limiter(SimpleNamespace(id="user-1"))

    assert list(limiter.clients) == ["user-1"]


def test_db_rate_limiter_allows_within_limit(monkeypatch) -> None:
    session = MagicMock()
    session.execute.side_effect = [None, SimpleNamespace(scalar_one=lambda: 1)]
    limiter = ratelimit.DbRateLimiter(limit=2, window=60, action="login")
    limiter._db = FakeDb(session)
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)
    monkeypatch.setattr(ratelimit.time, "time", lambda: 100)

    limiter.check("127.0.0.1")

    assert session.execute.call_count == 2


def test_db_rate_limiter_raises_over_limit(monkeypatch) -> None:
    session = MagicMock()
    session.execute.side_effect = [None, SimpleNamespace(scalar_one=lambda: 3)]
    limiter = ratelimit.DbRateLimiter(limit=2, window=60, action="login")
    limiter._db = FakeDb(session)
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)
    monkeypatch.setattr(ratelimit.time, "time", lambda: 100)

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("127.0.0.1")

    assert exc_info.value.status_code == 429


def test_db_rate_limiter_dependency_helpers(monkeypatch) -> None:
    limiter = ratelimit.DbRateLimiter(limit=2, window=60, action="login")
    check_spy = MagicMock()
    monkeypatch.setattr(limiter, "check", check_spy)
    limiter(MockRequest(client_host="10.0.0.1"))
    check_spy.assert_called_once_with("10.0.0.1")
    assert limiter.reset() is None

    auth_limiter = ratelimit.DbAuthenticatedRateLimiter(limit=2, window=60, action="content")
    auth_check_spy = MagicMock()
    monkeypatch.setattr(auth_limiter, "check", auth_check_spy)
    auth_limiter(SimpleNamespace(id="user-1"))
    auth_check_spy.assert_called_once_with("user-1")


def test_create_limiter_selects_expected_implementation(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("GSP_USE_MEMORY_RATELIMIT", raising=False)
    assert ratelimit._use_db_rate_limiting() is True

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
    assert ratelimit._use_db_rate_limiting() is False

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("GSP_USE_MEMORY_RATELIMIT", "1")
    assert ratelimit._use_db_rate_limiting() is False

    monkeypatch.setattr(ratelimit, "_use_db_rate_limiting", lambda: True)
    assert isinstance(ratelimit._create_limiter(1, 60, "login"), ratelimit.DbRateLimiter)
    assert isinstance(ratelimit._create_limiter(1, 60, "login", authenticated=True), ratelimit.DbAuthenticatedRateLimiter)

    monkeypatch.setattr(ratelimit, "_use_db_rate_limiting", lambda: False)
    assert isinstance(ratelimit._create_limiter(1, 60, "login"), ratelimit.RateLimiter)
    assert isinstance(ratelimit._create_limiter(1, 60, "login", authenticated=True), ratelimit.AuthenticatedRateLimiter)
