from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

BoundedFactText = Annotated[str, Field(min_length=1, max_length=2_000)]
BoundedSocialTitle = Annotated[str, Field(min_length=1, max_length=160)]
BoundedSocialDescription = Annotated[str, Field(min_length=1, max_length=2_000)]
Percentage = Annotated[int, Field(strict=True, ge=0, le=100)]
ClaimCount = Annotated[int, Field(strict=True, ge=0, le=100)]
Hashtag = Annotated[
    str,
    Field(min_length=2, max_length=64, pattern=r"^#[\w]+$"),
]


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

class FactCheckItemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mistake_el: BoundedFactText
    mistake_en: BoundedFactText
    correction_el: BoundedFactText
    correction_en: BoundedFactText
    explanation_el: BoundedFactText
    explanation_en: BoundedFactText
    severity: Literal["minor", "medium", "major"]
    confidence: Percentage
    real_life_example_el: BoundedFactText
    real_life_example_en: BoundedFactText
    scientific_evidence_el: BoundedFactText
    scientific_evidence_en: BoundedFactText


class FactCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[FactCheckItemSchema], Field(max_length=3)]
    truth_score: Percentage
    supported_claims_pct: Percentage
    claims_checked: ClaimCount
    balance: int | None = None

    @model_validator(mode="after")
    def checked_claims_cover_reported_errors(self) -> Self:
        """A response cannot report more errors than claims it checked."""
        if self.claims_checked < len(self.items):
            raise ValueError("claims_checked must cover every reported item")
        return self


class SocialCopySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title_el: BoundedSocialTitle
    title_en: BoundedSocialTitle
    description_el: BoundedSocialDescription
    description_en: BoundedSocialDescription
    hashtags: Annotated[list[Hashtag], Field(min_length=1, max_length=14)]

    @field_validator("hashtags")
    @classmethod
    def hashtags_are_unique(cls, hashtags: list[str]) -> list[str]:
        """Reject duplicate provider tags instead of charging for noisy output."""
        normalized = [hashtag.casefold() for hashtag in hashtags]
        if len(normalized) != len(set(normalized)):
            raise ValueError("hashtags must be unique")
        return hashtags


class SocialCopyResponse(BaseModel):
    social_copy: SocialCopySchema
    balance: int | None = None
