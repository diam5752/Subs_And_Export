from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.observability import ObservabilityStore, route_bucket


class FakeClock:
    def __init__(self, value: float = 10_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_store_never_persists_presence_or_user_identifier(tmp_path: Path) -> None:
    clock = FakeClock()
    store = ObservabilityStore(
        data_dir=tmp_path,
        enabled=True,
        retention_hours=24,
        presence_ttl_seconds=90,
        clock=clock,
    )

    store.record_presence(
        presence_id="runtime-browser-1234",
        user_id="secret-user-id",
        route="studio",
        viewport="wide",
    )
    store.record_event(
        kind="action",
        name="export_started",
        route="studio",
        auth_state="authenticated",
        outcome="started",
        export_format="1080p",
    )

    stored = store.path.read_text(encoding="utf-8")
    assert "secret-user-id" not in stored
    assert "runtime-browser-1234" not in stored
    assert "export_started" in stored
    assert store.snapshot()["active"]["authenticated_accounts"] == 1


def test_retention_and_presence_windows_are_bounded(tmp_path: Path) -> None:
    clock = FakeClock()
    store = ObservabilityStore(
        data_dir=tmp_path,
        enabled=True,
        retention_hours=24,
        presence_ttl_seconds=90,
        clock=clock,
    )
    store.record_event(
        kind="action",
        name="app_opened",
        route="studio",
        auth_state="guest",
    )
    store.record_presence(
        presence_id="runtime-browser-1234",
        user_id=None,
        route="studio",
        viewport="compact",
    )

    clock.value += (24 * 3_600) + 91
    snapshot = store.snapshot()

    assert snapshot["recent"] == []
    assert snapshot["active"]["estimated_total"] == 0


def test_presence_transition_replaces_the_same_browser_session(tmp_path: Path) -> None:
    store = ObservabilityStore(
        data_dir=tmp_path,
        enabled=True,
        retention_hours=24,
        presence_ttl_seconds=90,
    )
    common = {
        "presence_id": "runtime-browser-1234",
        "route": "studio",
        "viewport": "regular",
    }

    store.record_presence(user_id=None, **common)
    store.record_presence(user_id="secret-user-id", **common)
    signed_in = store.snapshot()["active"]

    assert signed_in["authenticated_accounts"] == 1
    assert signed_in["guest_browser_sessions"] == 0
    assert signed_in["estimated_total"] == 1

    store.record_presence(user_id=None, **common)
    signed_out = store.snapshot()["active"]

    assert signed_out["authenticated_accounts"] == 0
    assert signed_out["guest_browser_sessions"] == 1
    assert signed_out["estimated_total"] == 1


def test_snapshot_groups_sanitized_errors(tmp_path: Path) -> None:
    store = ObservabilityStore(
        data_dir=tmp_path,
        enabled=True,
        retention_hours=24,
        presence_ttl_seconds=90,
    )
    for _ in range(2):
        store.record_backend_error(route="videos", status_code=500)

    snapshot = store.snapshot()

    assert snapshot["errors"] == [{
        "kind": "backend_error",
        "name": "http_5xx",
        "route": "videos",
        "status_code": 500,
        "count": 2,
    }]
    assert all("message" not in json.dumps(item) for item in snapshot["recent"])


def test_route_bucket_removes_identifiers() -> None:
    assert route_bucket("/videos/jobs/private-job-id/export") == "videos"
    assert route_bucket("/static/artifacts/private-job-id/output.mp4") == "media"
    assert route_bucket("/unexpected/private-value") == "other"
