import json
import os
from pathlib import Path

from backend.app.core import metrics


def test_env_bool_handles_unknown(monkeypatch):
    monkeypatch.setenv("PIPELINE_LOGGING", "maybe")
    assert metrics._env_bool("PIPELINE_LOGGING") is None


def test_should_log_metrics_respects_flags(monkeypatch) -> None:
    monkeypatch.delenv("PIPELINE_LOGGING", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    original = os.environ.get("PYTEST_CURRENT_TEST")
    os.environ["PYTEST_CURRENT_TEST"] = "test"
    try:
        assert metrics.should_log_metrics() is False

        monkeypatch.setenv("PIPELINE_LOGGING", "1")
        assert metrics.should_log_metrics() is True

        monkeypatch.setenv("PIPELINE_LOGGING", "0")
        assert metrics.should_log_metrics() is False
    finally:
        if original is not None:
            os.environ["PYTEST_CURRENT_TEST"] = original
        else:
            os.environ.pop("PYTEST_CURRENT_TEST", None)


def test_should_log_metrics_defaults_to_dev(monkeypatch) -> None:
    original = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        monkeypatch.delenv("PIPELINE_LOGGING", raising=False)
        monkeypatch.setenv("APP_ENV", "dev")
        assert metrics.should_log_metrics() is True
    finally:
        if original is not None:
            os.environ["PYTEST_CURRENT_TEST"] = original


def test_log_pipeline_metrics_writes_jsonl(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("PIPELINE_LOGGING", "1")
    monkeypatch.setenv("PIPELINE_LOG_PATH", str(log_path))
    metrics.log_pipeline_metrics({"status": "success", "timings": {"total_s": 1.23}})

    data = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(data) == 1
    parsed = json.loads(data[0])
    assert parsed["status"] == "success"
    assert parsed["timings"]["total_s"] == 1.23
    assert "ts" in parsed and "host" in parsed


def test_log_pipeline_metrics_handles_errors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PIPELINE_LOGGING", "1")
    monkeypatch.delenv("PIPELINE_LOG_PATH", raising=False)

    class DummyPath:
        def __init__(self, path: Path):
            self._path = Path(path)
            self.parent = self._path.parent

        def open(self, *args, **kwargs):
            raise OSError("boom")

    monkeypatch.setattr(metrics, "_resolve_log_path", lambda: DummyPath(tmp_path / "boom"))
    metrics.log_pipeline_metrics({"status": "fail"})


def test_resolve_log_path_defaults(monkeypatch):
    monkeypatch.delenv("PIPELINE_LOG_PATH", raising=False)
    path = metrics._resolve_log_path()
    assert path.name == "pipeline_metrics.jsonl"
