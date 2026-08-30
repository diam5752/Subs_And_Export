from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    progress: int
    message: str | None
    created_at: int
    updated_at: int
    expires_at: int | None = None
    result_data: dict[str, Any] | None
    balance: int | None = None


class PaginatedJobsResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class BatchDeleteRequest(BaseModel):
    job_ids: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=50)]


class BatchDeleteResponse(BaseModel):
    status: str
    deleted_count: int
    job_ids: list[str]
