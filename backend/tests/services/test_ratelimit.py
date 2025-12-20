"""Tests for rate limiting implementation."""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.app.core.ratelimit import (
    RateLimiter,
    AuthenticatedRateLimiter,
    get_client_ip,
)


class MockRequest:
    """Mock FastAPI Request object."""
    
    def __init__(self, client_host: str | None = None, headers: dict | None = None):
        self.client = MagicMock()
        self.client.host = client_host
        self.headers = headers or {}
    
    def __getattr__(self, name):
        if name == "headers":
            return self.headers
        return getattr(self.client, name)


class TestGetClientIp:
    """Test IP extraction from requests."""
    
    def test_client_host(self) -> None:
        request = MockRequest(client_host="192.168.1.1")
        assert get_client_ip(request) == "192.168.1.1"
    
    def test_forwarded_for_single(self) -> None:
        request = MockRequest(client_host=None, headers={"x-forwarded-for": "10.0.0.1"})
        request.client.host = None
        assert get_client_ip(request) == "10.0.0.1"
    
    def test_forwarded_for_multiple(self) -> None:
        request = MockRequest(
            client_host=None, 
            headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2, 192.168.1.1"}
        )
        request.client.host = None
        # Should take last IP (rightmost)
        assert get_client_ip(request) == "192.168.1.1"
    
    def test_real_ip_header(self) -> None:
        request = MockRequest(client_host=None, headers={"x-real-ip": "172.16.0.1"})
        request.client.host = None
        assert get_client_ip(request) == "172.16.0.1"
    
    def test_fallback_unknown(self) -> None:
        request = MockRequest(client_host=None, headers={})
        request.client = None
        assert get_client_ip(request) == "unknown"


class TestInMemoryRateLimiter:
    """Test in-memory rate limiter (used in tests)."""

    @pytest.fixture(autouse=True)
    def enable_ratelimit(self, monkeypatch):
        monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)
    
    def test_allows_within_limit(self) -> None:
        limiter = RateLimiter(limit=5, window=60)
        request = MockRequest(client_host="192.168.1.1")
        
        # Should allow 5 requests
        for _ in range(5):
            limiter(request)  # Should not raise
    
    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(limit=3, window=60)
        request = MockRequest(client_host="192.168.1.1")
        
        # Allow first 3
        for _ in range(3):
            limiter(request)
        
        # 4th should raise
        with pytest.raises(HTTPException) as exc_info:
            limiter(request)
        
        assert exc_info.value.status_code == 429
        assert "Too many requests" in exc_info.value.detail
    
    def test_different_ips_separate_limits(self) -> None:
        limiter = RateLimiter(limit=2, window=60)
        request1 = MockRequest(client_host="192.168.1.1")
        request2 = MockRequest(client_host="192.168.1.2")
        
        # IP1 uses its limit
        for _ in range(2):
            limiter(request1)
        
        # IP2 should still work
        limiter(request2)
        
        # IP1 should be blocked
        with pytest.raises(HTTPException):
            limiter(request1)
    
    def test_reset_clears_state(self) -> None:
        limiter = RateLimiter(limit=2, window=60)
        request = MockRequest(client_host="192.168.1.1")
        
        for _ in range(2):
            limiter(request)
        
        limiter.reset()
        
        # Should work again after reset
        limiter(request)


class TestAuthenticatedRateLimiter:
    """Test user-based rate limiter."""
    
    def test_uses_user_id(self) -> None:
        limiter = AuthenticatedRateLimiter(limit=2, window=60)
        
        user1 = MagicMock()
        user1.id = "user-1"
        
        user2 = MagicMock()
        user2.id = "user-2"
        
        # User1 uses limit
        with patch("backend.app.core.ratelimit.get_current_user", return_value=user1):
            limiter(user1)
            limiter(user1)
        
        # User2 should work
        with patch("backend.app.core.ratelimit.get_current_user", return_value=user2):
            limiter(user2)
        
        # User1 should be blocked
        with pytest.raises(HTTPException) as exc_info:
            limiter(user1)
        
        assert exc_info.value.status_code == 429
