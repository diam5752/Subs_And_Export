from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, Field


class JobResponse(BaseModel):
    model_config = {'from_attributes': True}

    id: str
    status: str
    progress: int
    message: Optional[str]
    created_at: int
    updated_at: int
    result_data: Optional[Dict]

class PaginatedJobsResponse(BaseModel):
    items: List[JobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

class BatchDeleteRequest(BaseModel):
    job_ids: List[Annotated[str, Field(max_length=64)]]

class BatchDeleteResponse(BaseModel):
    status: str
    deleted_count: int
    job_ids: List[str]

class ViralMetadataResponse(BaseModel):
    hooks: List[str]
    caption_hook: str
    caption_body: str
    cta: str
    hashtags: List[str]

