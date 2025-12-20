"""Rate limiting utilities with DB-backed storage for multi-instance correctness.

This module provides both in-memory (for tests) and PostgreSQL-backed rate limiting
to ensure rate limits work correctly across Cloud Run instances.
"""

from __future__ import annotations

import ipaddress
import os
import time
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..api.deps import get_current_user
from ..db.models import DbRateLimit
from .auth import User

if TYPE_CHECKING:
    from .database import Database


def get_client_ip(request: Request) -> str:
    """
    Best-effort client IP extraction safe for proxy environments.

    Cloud Run (and most reverse proxies) append the connecting client's IP to the
    right side of ``X-Forwarded-For``. We therefore take the *last* hop to reduce
    spoofing risk from client-supplied leading values.
    """
    if request.client and request.client.host:
        return request.client.host

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        parts = [part.strip() for part in x_forwarded_for.split(",") if part.strip()]
        if parts:
            candidate = parts[-1]
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        try:
            return str(ipaddress.ip_address(x_real_ip.strip()))
        except ValueError:
            pass

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimiter:
    """In-memory rate limiter (fast but per-process, for tests/dev)."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.clients: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        if os.environ.get("GSP_DISABLE_RATELIMIT") == "1":
            return

        # Basic protection against memory exhaustion
        if len(self.clients) > 10000:
            self.clients.clear()

        now = time.time()
        # Filter out old timestamps
        history = [t for t in self.clients.get(key, []) if now - t < self.window]

        if len(history) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        history.append(now)
        self.clients[key] = history

    def __call__(self, request: Request):
        ip = get_client_ip(request)
        self.check(ip)

    def reset(self):
        self.clients.clear()


class AuthenticatedRateLimiter(RateLimiter):
    """Rate limiter that uses User ID instead of IP."""

    def __call__(self, user: User = Depends(get_current_user)):
        # Basic protection against memory exhaustion
        if len(self.clients) > 10000:
            self.clients.clear()

        # Use User ID as key
        key = user.id
        now = time.time()

        # Filter out old timestamps
        history = [t for t in self.clients.get(key, []) if now - t < self.window]

        if len(history) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        history.append(now)
        self.clients[key] = history


class DbRateLimiter:
    """DB-backed rate limiter for multi-instance correctness (Cloud Run)."""

    def __init__(self, limit: int, window: int, action: str = "request"):
        self.limit = limit
        self.window = window
        self.action = action
        self._db: Database | None = None

    def _get_db(self) -> Database:
        """Lazy database connection."""
        if self._db is None:
            from .database import Database
            self._db = Database()
        return self._db

    def check(self, key: str) -> None:
        """Check rate limit for a key, raising 429 if exceeded."""
        if os.environ.get("GSP_DISABLE_RATELIMIT") == "1":
            return

        db = self._get_db()
        now = int(time.time())
        min_window_start = now - self.window
        expires_at = now + self.window

        full_key = f"{self.action}:{key}"

        with db.session() as session:
            # Clean up expired entries
            session.execute(
                text("DELETE FROM rate_limits WHERE expires_at < :now"),
                {"now": now},
            )

            # Upsert with atomic increment using raw SQL
            result = session.execute(
                text("""
                    INSERT INTO rate_limits (key, count, window_start, expires_at)
                    VALUES (:key, 1, :now, :expires_at)
                    ON CONFLICT (key) DO UPDATE SET
                        count = CASE 
                            WHEN rate_limits.window_start < :min_ws THEN 1 
                            ELSE rate_limits.count + 1 
                        END,
                        window_start = CASE 
                            WHEN rate_limits.window_start < :min_ws THEN :now 
                            ELSE rate_limits.window_start 
                        END,
                        expires_at = :expires_at
                    RETURNING count
                """),
                {
                    "key": full_key,
                    "now": now,
                    "expires_at": expires_at,
                    "min_ws": min_window_start,
                },
            )
            current_count = result.scalar_one()

        if current_count > self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

    def __call__(self, request: Request):
        """FastAPI dependency for IP-based rate limiting."""
        ip = get_client_ip(request)
        self.check(ip)

    def reset(self):
        """Clear rate limit state (for tests). In production this is a no-op."""
        # In production with DB, clearing isn't needed; entries expire naturally.
        # This method exists for API compatibility with in-memory limiter.
        pass


class DbAuthenticatedRateLimiter(DbRateLimiter):
    """DB-backed rate limiter using User ID."""

    def __call__(self, user: User = Depends(get_current_user)):
        self.check(user.id)


def _use_db_rate_limiting() -> bool:
    """Check if DB rate limiting should be used (production mode)."""
    return os.getenv("PYTEST_CURRENT_TEST") is None and os.getenv("GSP_USE_MEMORY_RATELIMIT") != "1"


# Factory functions to choose implementation based on environment
def _create_limiter(limit: int, window: int, action: str, authenticated: bool = False):
    """Create appropriate rate limiter based on environment."""
    if _use_db_rate_limiting():
        if authenticated:
            return DbAuthenticatedRateLimiter(limit=limit, window=window, action=action)
        return DbRateLimiter(limit=limit, window=window, action=action)
    else:
        if authenticated:
            return AuthenticatedRateLimiter(limit=limit, window=window)
        return RateLimiter(limit=limit, window=window)


# 5 login attempts per minute per IP
limiter_login = _create_limiter(limit=5, window=60, action="login")

# 3 registration attempts per minute per IP to prevent spam
limiter_register = _create_limiter(limit=3, window=60, action="register")

# Daily signup limit per IP (anti-abuse)
limiter_signup_daily = _create_limiter(limit=5, window=86400, action="signup_daily")

# 10 processing attempts per minute per USER to prevent DoS via file uploads
limiter_processing = _create_limiter(limit=10, window=60, action="processing", authenticated=True)

# 10 content generation attempts per minute per USER
limiter_content = _create_limiter(limit=10, window=60, action="content", authenticated=True)

# 5 account modifications per minute per USER (password, name, delete)
limiter_auth_change = _create_limiter(limit=5, window=60, action="auth_change", authenticated=True)

# Static file rate limiting per IP
limiter_static = _create_limiter(limit=60, window=60, action="static")
