import builtins
from pathlib import Path

import pytest

import app as streamlit_app


def test_log_ui_error_logs_event(monkeypatch) -> None:
    logged = {}

    def fake_log(event):
        logged.update(event)

    monkeypatch.setattr(streamlit_app.metrics, "log_pipeline_metrics", fake_log)

    try:
        raise RuntimeError("boom")
    except Exception as exc:  # noqa: BLE001
        streamlit_app._log_ui_error(exc, {"foo": "bar"})

    assert logged["status"] == "error"
    assert "RuntimeError" in logged["error"]
    assert logged["foo"] == "bar"
