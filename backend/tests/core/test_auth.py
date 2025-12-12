
import pytest
import os
from backend.app.core import auth

def test_verify_password_scrypt_error():
    """Test verification handles scrypt errors gracefully."""
    # Malformed scrypt string
    malformed = "scrypt$1$1$1$salt$badhash"
    assert not auth._verify_password("password", malformed)

    # Missing parts
    assert not auth._verify_password("password", "scrypt$incomplete")

def test_get_secret_fallback(monkeypatch, tmp_path):
    """Test secret resolution priority."""
    # 1. Env var
    monkeypatch.setenv("TEST_SECRET", "env_value")
    assert auth._get_secret("TEST_SECRET") == "env_value"
    
    # 2. File
    monkeypatch.delenv("TEST_SECRET")
    secrets_file = tmp_path / "secrets.toml"
    secrets_file.write_text('TEST_SECRET = "file_value"')
    
    # Mock PROJECT_ROOT navigation
    # Defaults traverse parent.parent/config
    # We can just enforce GSP_SECRETS_FILE
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_file))
    
    assert auth._get_secret("TEST_SECRET") == "file_value"
    
    # 3. Missing
    monkeypatch.delenv("GSP_SECRETS_FILE")
    # Also ensure default path doesn't exist or doesn't have it (safe assumption usually)
    # But clean approach: Mock logic or ensure env is clean.
    assert auth._get_secret("NONEXISTENT_SECRET") is None

def test_google_oauth_config_missing(monkeypatch):
    """Test returns None when config missing."""
    # Disable file-based secrets to ensure we only test env vars
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SITE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_APP_URL", raising=False)
    assert auth.google_oauth_config() is None
