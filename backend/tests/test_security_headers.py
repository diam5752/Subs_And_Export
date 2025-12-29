
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_cache_control_headers_sensitive_endpoints():
    """Verify that sensitive endpoints return Cache-Control: no-store."""
    sensitive_paths = [
        "/auth/login", # While this is POST, checking the path logic is enough
        "/videos/jobs/fake-id",
        "/history",
        "/jobs"
    ]

    for path in sensitive_paths:
        # We don't care about the actual response status (401, 404, etc.)
        # The middleware should apply headers regardless.
        response = client.get(path)
        assert response.headers.get("Cache-Control") == "no-store", \
            f"Cache-Control header missing or incorrect for {path}"

def test_cache_control_headers_public_endpoints():
    """Verify that public/non-sensitive endpoints do NOT force no-store."""
    response = client.get("/health")
    # Health check should not strictly require no-store, though having it isn't bad.
    # But our logic specifically targets sensitive paths.
    # The default behavior is usually no header or standard caching.

    # If the middleware is working correctly, it should NOT set it for /health
    # unless some other component sets it.
    # Current implementation only adds it for specific prefixes.
    assert response.headers.get("Cache-Control") != "no-store", \
        "/health should not have Cache-Control: no-store forced by this middleware"
