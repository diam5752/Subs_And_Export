import json
import logging

from backend.app.core import auth, database
from backend.app.core.logging import JSONFormatter


def test_get_secret_prefers_env_over_file(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('MY_KEY = "file"')
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_path))
    monkeypatch.setenv("MY_KEY", "env-value")

    assert auth._get_secret("MY_KEY") == "env-value"


def test_get_secret_reads_local_file(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('MY_KEY = "file-value"\nOTHER = 1')
    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_path))

    assert auth._get_secret("MY_KEY") == "file-value"


def test_get_secret_respects_disable_flag(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.delenv("GSP_SECRETS_FILE", raising=False)

    assert auth._get_secret("MY_KEY") is None


def test_database_loads_invalid_json_returns_empty():
    assert database.Database.loads("not valid") == {}


def test_database_loads_accepts_only_json_objects():
    assert database.Database.loads('{"job_id":"job-1","attempt":2}') == {
        "job_id": "job-1",
        "attempt": 2,
    }
    assert database.Database.loads('["not", "an", "object"]') == {}


def test_json_formatter_preserves_request_correlation_id():
    record = logging.LogRecord(
        name="gsubs.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="processed",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-123"

    rendered = json.loads(JSONFormatter().format(record))

    assert rendered["request_id"] == "request-123"
