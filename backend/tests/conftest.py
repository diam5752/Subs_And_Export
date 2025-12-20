import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Set trusted hosts BEFORE any app import
os.environ.setdefault("GSP_TRUSTED_HOSTS", "localhost,testserver")
os.environ.setdefault("APP_ENV", "dev")

# Set default test database URL (use separate test database)
os.environ.setdefault("GSP_DATABASE_URL", "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test")

# Force memory-based rate limiting for tests to avoid state persistence/429s (DbRateLimiter.reset() is no-op)
os.environ["GSP_USE_MEMORY_RATELIMIT"] = "1"
# COMPLETELY DISABLE rate limiting to prevent tests from blocking each other (shared IP)
os.environ["GSP_DISABLE_RATELIMIT"] = "1"

# Mock modules that require compilation/heavy install
sys.modules["faster_whisper"] = MagicMock()
sys.modules["stable_whisper"] = MagicMock()
sys.modules["pydub"] = MagicMock()


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create test database and run migrations before tests."""
    import subprocess
    test_db_url = os.environ.get("GSP_DATABASE_URL", "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test")
    
    # Create the test database if it doesn't exist
    try:
        import psycopg
        # Parse URL to get connection details
        # Format: postgresql+psycopg://user:pass@host:port/dbname
        parts = test_db_url.replace("postgresql+psycopg://", "").split("/")
        dbname = parts[-1] if len(parts) > 1 else "gsp_test"
        host_part = parts[0]
        
        # Connect to postgres database to create test db
        user_pass, host_port = host_part.split("@")
        user, password = user_pass.split(":")
        host, port = host_port.split(":")
        
        with psycopg.connect(f"postgresql://{user}:{password}@{host}:{port}/postgres", autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'")
                if not cur.fetchone():
                    cur.execute(f"CREATE DATABASE {dbname}")
    except Exception as e:
        print(f"Note: Could not auto-create test database: {e}")
    
    # Run migrations
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        text=True,
        env={**os.environ, "GSP_DATABASE_URL": test_db_url}
    )
    if result.returncode != 0:
        print(f"Migration warning: {result.stderr}")
    
    yield
    
    # Cleanup: optionally drop tables after all tests
    # (commented out to preserve test data for debugging)
    # from backend.app.db.base import Base
    # from backend.app.core.database import Database
    # db = Database(url=test_db_url)
    # Base.metadata.drop_all(db.engine)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GSP_TRUSTED_HOSTS", "*")  # Allow test client requests

    from backend.app.api.endpoints import videos as videos_endpoints
    from backend.app.core import ratelimit
    from backend.app.services.ffmpeg_utils import MediaProbe
    from backend.main import app

    # specific methods, but checking logic is what raises 429.
    # We MUST patch the CLASS __call__ method because special dunder methods 
    # are looked up on the type, not the instance.
    
    noop = lambda *args, **kwargs: None
    monkeypatch.setattr(ratelimit.RateLimiter, "__call__", noop)
    monkeypatch.setattr(ratelimit.AuthenticatedRateLimiter, "__call__", noop)
    monkeypatch.setattr(ratelimit.DbRateLimiter, "__call__", noop)
    monkeypatch.setattr(ratelimit.DbAuthenticatedRateLimiter, "__call__", noop)

    # We also keep resets just in case logic leaks, but disabling check is key.
    ratelimit.limiter_login.reset()
    ratelimit.limiter_register.reset()

    monkeypatch.setattr(
        videos_endpoints,
        "probe_media",
        lambda _path: MediaProbe(duration_s=10.0, audio_codec="aac"),
    )

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_auth_headers(client: TestClient) -> dict[str, str]:
    import secrets
    # Use unique email per test to avoid conflicts
    email = f"test_{secrets.token_hex(4)}@example.com"
    password = "testpassword123"

    client.post("/auth/register", json={"email": email, "password": password, "name": "Test User"})
    token = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def prevent_paid_api_calls(monkeypatch):
    """
    Prevent tests from making expensive API calls.
    1. Remove API keys from environment.
    2. Mock secrets loading to prevent leaking keys from secrets.toml.
    3. Patch internal resolvers to always return None.
    """
    # 1. Strip Env Vars
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    # 2. Block secrets.toml access
    # We patch toml.load to return empty dict wherever it might be used for secrets.
    # Currently subtitles.py is the main consumer.
    try:
        monkeypatch.setattr("backend.app.services.subtitles.toml.load", lambda x: {})
    except (ImportError, AttributeError):
        pass

    # 3. Patch specific key resolvers in known modules
    # These override the logic to ALWAYS return None unless set by test env var (which we deleted)
    try:
        monkeypatch.setattr("backend.app.services.subtitles._resolve_openai_api_key", lambda *args: None)
        monkeypatch.setattr("backend.app.services.subtitles._resolve_groq_api_key", lambda *args: None)
    except (ImportError, AttributeError):
        pass
        
    try:
        monkeypatch.setattr("backend.app.services.transcription.openai_cloud._resolve_openai_api_key", lambda *args: None)
        monkeypatch.setattr("backend.app.services.transcription.groq_cloud._resolve_groq_api_key", lambda *args: None)
    except (ImportError, AttributeError):
        pass
