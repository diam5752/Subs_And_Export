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
    mistake_el: str
    mistake_en: str
    correction_el: str
    correction_en: str
    explanation_el: str
    explanation_en: str
    severity: str  # minor | medium | major
    confidence: int  # 0-100
    real_life_example_el: str  # Concrete example disproving the claim
    real_life_example_en: str
    scientific_evidence_el: str  # Scientific explanation/citation
    scientific_evidence_en: str


class FactCheckResponse(BaseModel):
    items: List[FactCheckItemSchema]
    truth_score: int  # 0-100 overall accuracy
    supported_claims_pct: int  # 0-100 percent supported
    claims_checked: int  # Total claims analyzed
    balance: int | None = None


class SocialCopySchema(BaseModel):
    title_el: str
    title_en: str
    description_el: str
    description_en: str
    hashtags: List[str]


class SocialCopyResponse(BaseModel):
    social_copy: SocialCopySchema
    balance: int | None = None
