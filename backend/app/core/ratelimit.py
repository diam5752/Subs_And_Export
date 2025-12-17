import ipaddress
import time

from fastapi import Depends, HTTPException, Request, status

from ..api.deps import get_current_user
from .auth import User


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
    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.clients: dict[str, list[float]] = {}

    def __call__(self, request: Request):
        # Basic protection against memory exhaustion
        if len(self.clients) > 10000:
            self.clients.clear()

        ip = get_client_ip(request)
        now = time.time()
        # Filter out old timestamps
        history = [t for t in self.clients.get(ip, []) if now - t < self.window]

        if len(history) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        history.append(now)
        self.clients[ip] = history

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


# 5 login attempts per minute per IP
limiter_login = RateLimiter(limit=5, window=60)

# 3 registration attempts per minute per IP to prevent spam
limiter_register = RateLimiter(limit=3, window=60)

# 10 processing attempts per minute per USER to prevent DoS via file uploads
# Changed to AuthenticatedRateLimiter to prevent shared IP blocking on Cloud Run
limiter_processing = AuthenticatedRateLimiter(limit=10, window=60)

# 10 content generation attempts per minute per USER
# Changed to AuthenticatedRateLimiter to prevent shared IP blocking on Cloud Run
limiter_content = AuthenticatedRateLimiter(limit=10, window=60)
