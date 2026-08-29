from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.services.observability import ObservabilityStore


def install_store(client: TestClient, tmp_path: Path) -> ObservabilityStore:
    store = ObservabilityStore(
        data_dir=tmp_path,
        enabled=True,
        retention_hours=168,
        presence_ttl_seconds=90,
    )
    client.app.state.observability = store
    return store


def test_anonymous_event_schema_is_content_free(
    client: TestClient,
    tmp_path: Path,
) -> None:
    store = install_store(client, tmp_path)

    accepted = client.post("/observability/events", json={
        "kind": "action",
        "name": "export_started",
        "outcome": "started",
        "export_format": "1080p",
        "route": "studio",
        "viewport": "wide",
    })
    rejected = client.post("/observability/events", json={
        "kind": "frontend_error",
        "name": "window_error",
        "message": "private subtitle content",
        "route": "studio",
        "viewport": "wide",
    })

    assert accepted.status_code == 204
    assert rejected.status_code == 422
    assert "private subtitle content" not in store.path.read_text(encoding="utf-8")


def test_presence_deduplicates_authenticated_account_without_persistence(
    client: TestClient,
    user_auth_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    store = install_store(client, tmp_path)
    payload = {
        "kind": "presence",
        "presence_id": "runtime-browser-1234",
        "route": "studio",
        "viewport": "regular",
    }

    assert client.post("/observability/events", headers=user_auth_headers, json=payload).status_code == 204
    payload["presence_id"] = "second-browser-5678"
    assert client.post("/observability/events", headers=user_auth_headers, json=payload).status_code == 204

    assert store.snapshot()["active"]["authenticated_accounts"] == 1
    assert store.path.read_text(encoding="utf-8") == ""


def test_snapshot_requires_dedicated_admin_and_is_not_cached(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    store = install_store(client, tmp_path)
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    monkeypatch.setattr(settings, "observability_admin_user_ids", [])
    denied = client.get("/observability/admin/snapshot", headers=user_auth_headers)

    monkeypatch.setattr(settings, "observability_admin_user_ids", [user_id])
    store.record_event(
        kind="api_error",
        name="http_5xx",
        route="studio",
        auth_state="authenticated",
        status_code=500,
    )
    allowed = client.get("/observability/admin/snapshot", headers=user_auth_headers)

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "private, no-store"
    assert allowed.json()["errors"][0]["name"] == "http_5xx"
    assert user_id not in allowed.text
