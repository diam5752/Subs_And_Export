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
    balance: int | None = None

class PaginatedJobsResponse(BaseModel):
    items: List[JobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

class BatchDeleteRequest(BaseModel):
    job_ids: Annotated[List[Annotated[str, Field(max_length=64)]], Field(max_length=50)]

class BatchDeleteResponse(BaseModel):
    status: str
    deleted_count: int
    job_ids: List[str]




class FactCheckItemSchema(BaseModel):
    mistake: str
    correction: str
    explanation: str
    severity: str  # minor | medium | major
    confidence: int  # 0-100
    real_life_example: str  # Concrete example disproving the claim
    scientific_evidence: str  # Scientific explanation/citation


class FactCheckResponse(BaseModel):
    items: List[FactCheckItemSchema]
    truth_score: int  # 0-100 overall accuracy
    supported_claims_pct: int  # 0-100 percent supported
    claims_checked: int  # Total claims analyzed
    balance: int | None = None


class SocialCopySchema(BaseModel):
    title: str
    description: str
    hashtags: List[str]


class SocialCopyResponse(BaseModel):
    social_copy: SocialCopySchema
    balance: int | None = None
