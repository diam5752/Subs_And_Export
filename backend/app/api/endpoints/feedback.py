"""Anonymous-or-authenticated product feedback endpoint."""

from __future__ import annotations

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.deps import get_feedback_store, get_optional_current_user
from backend.app.core.auth import User
from backend.app.core.ratelimit import (
    get_client_ip,
    limiter_feedback_hour,
    limiter_feedback_minute,
)
from backend.app.services.product_feedback import FeedbackInputError, FeedbackStore

router = APIRouter()

_MIN_FORM_AGE_SECONDS = 2
_MAX_FORM_AGE_SECONDS = 4 * 60 * 60


class FeedbackSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category: Literal["idea", "bug", "complaint", "chat"]
    message: str = Field(min_length=1, max_length=4_000)
    source_path: str = Field(min_length=1, max_length=2_048)
    page_title: str = Field(default="GSUBS", max_length=512)
    form_started_at: int = Field(gt=0)
    website: str = Field(default="", max_length=512)


class FeedbackResponse(BaseModel):
    status: Literal["received"] = "received"
    id: str | None


@router.post(
    "",
    response_model=FeedbackResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(limiter_feedback_minute),
        Depends(limiter_feedback_hour),
    ],
)
def submit_feedback(
    payload: FeedbackSubmission,
    request: Request,
    store: Annotated[FeedbackStore, Depends(get_feedback_store)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> FeedbackResponse:
    """Persist feedback first; notification delivery happens asynchronously."""
    # A populated hidden field receives the same public response but never
    # reaches storage or email, which avoids turning the guard into an oracle.
    if payload.website.strip():
        return FeedbackResponse(id=None)

    now = int(time.time())
    form_age = now - payload.form_started_at
    if form_age < _MIN_FORM_AGE_SECONDS or form_age > _MAX_FORM_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Please reopen the feedback form and try again.",
        )

    try:
        receipt = store.submit(
            category=payload.category,
            message=payload.message,
            source_path=payload.source_path,
            page_title=payload.page_title,
            submitter=current_user,
            client_ip=get_client_ip(request),
            now=now,
        )
    except FeedbackInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return FeedbackResponse(id=receipt.id)
