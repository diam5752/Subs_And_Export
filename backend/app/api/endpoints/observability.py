"""Content-free event intake and owner-only operational dashboard API."""

from __future__ import annotations

import hmac
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ...core.auth import User
from ...core.config import settings
from ...core.ratelimit import limiter_observability
from ...services.jobs import JobStore
from ...services.observability import ObservabilityStore
from ..deps import (
    get_current_user,
    get_job_store,
    get_observability_store,
    get_optional_current_user,
)

router = APIRouter()
RouteBucket = Literal[
    "studio", "auth", "account", "billing", "feedback", "observability", "legal", "other"
]
ViewportBucket = Literal["compact", "regular", "wide"]
ExportFormat = Literal["720p", "1080p", "4k", "srt", "vtt", "txt", "other"]


class _TelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RouteBucket
    viewport: ViewportBucket


class PresencePayload(_TelemetryPayload):
    kind: Literal["presence"]
    presence_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")


class ActionPayload(_TelemetryPayload):
    kind: Literal["action"]
    name: Literal[
        "app_opened",
        "file_selected",
        "processing_started",
        "processing_completed",
        "processing_failed",
        "export_started",
        "export_completed",
        "export_failed",
        "subtitle_saved",
        "feedback_opened",
        "feedback_submitted",
        "feedback_failed",
    ]
    outcome: Literal["observed", "started", "succeeded", "failed"] = "observed"
    export_format: ExportFormat | None = None


class ErrorPayload(_TelemetryPayload):
    kind: Literal["frontend_error", "api_error"]
    name: Literal[
        "window_error",
        "unhandled_rejection",
        "network_error",
        "request_timeout",
        "upload_network_error",
        "upload_timeout",
        "invalid_response",
        "http_4xx",
        "http_5xx",
        "unknown_error",
    ]
    status_code: int | None = Field(default=None, ge=0, le=599)


TelemetryPayload = Annotated[
    PresencePayload | ActionPayload | ErrorPayload,
    Field(discriminator="kind"),
]


class ActiveSnapshot(BaseModel):
    authenticated_accounts: int
    guest_browser_sessions: int
    estimated_total: int
    window_seconds: int


class ActionCount(BaseModel):
    name: str
    outcome: str
    export_format: str | None = None
    count: int


class ErrorCount(BaseModel):
    kind: str
    name: str
    route: str
    status_code: int | None = None
    count: int


class RecentEvent(BaseModel):
    ts: int
    kind: str
    name: str
    route: str
    auth_state: str
    outcome: str | None = None
    viewport: str | None = None
    export_format: str | None = None
    status_code: int | None = None


class ObservabilitySnapshot(BaseModel):
    generated_at: int
    retention_hours: int
    active: ActiveSnapshot
    totals: dict[str, int]
    jobs: dict[str, int]
    actions: list[ActionCount]
    errors: list[ErrorCount]
    recent: list[RecentEvent]


@router.post(
    "/events",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(limiter_observability)],
)
def record_event(
    payload: TelemetryPayload,
    current_user: User | None = Depends(get_optional_current_user),
    store: ObservabilityStore = Depends(get_observability_store),
) -> Response:
    """Accept only the fixed, content-free telemetry schema."""
    user_id = current_user.id if current_user is not None else None
    if isinstance(payload, PresencePayload):
        store.record_presence(
            presence_id=payload.presence_id,
            user_id=user_id,
            route=payload.route,
            viewport=payload.viewport,
        )
    else:
        store.record_event(
            kind=payload.kind,
            name=payload.name,
            route=payload.route,
            auth_state="authenticated" if user_id is not None else "guest",
            outcome=payload.outcome if isinstance(payload, ActionPayload) else None,
            viewport=payload.viewport,
            export_format=payload.export_format if isinstance(payload, ActionPayload) else None,
            status_code=payload.status_code if isinstance(payload, ErrorPayload) else None,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _assert_observability_admin(user: User) -> None:
    allowed = settings.observability_admin_user_ids
    if not allowed or not any(hmac.compare_digest(user.id, candidate) for candidate in allowed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


@router.get("/admin/snapshot", response_model=ObservabilitySnapshot)
def get_snapshot(
    response: Response,
    current_user: User = Depends(get_current_user),
    store: ObservabilityStore = Depends(get_observability_store),
    job_store: JobStore = Depends(get_job_store),
) -> ObservabilitySnapshot:
    _assert_observability_admin(current_user)
    snapshot = store.snapshot()
    since = int(time.time()) - (store.retention_hours * 3_600)
    snapshot["jobs"] = job_store.count_jobs_by_status_since(since)
    response.headers["Cache-Control"] = "private, no-store"
    return ObservabilitySnapshot.model_validate(snapshot)
