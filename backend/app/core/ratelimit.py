import time

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.clients: dict[str, list[float]] = {}

    def __call__(self, request: Request):
        # Basic protection against memory exhaustion
        if len(self.clients) > 10000:
            self.clients.clear()

        ip = request.client.host if request.client else "unknown"
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

# 5 login attempts per minute per IP
limiter_login = RateLimiter(limit=5, window=60)

# 3 registration attempts per minute per IP to prevent spam
limiter_register = RateLimiter(limit=3, window=60)
