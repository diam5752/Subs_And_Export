from typing import Optional, Dict, List
from pydantic import BaseModel

class JobResponse(BaseModel):
    id: str
    status: str
    progress: int
    message: Optional[str]
    created_at: int
    updated_at: int
    result_data: Optional[Dict]

class ViralMetadataResponse(BaseModel):
    hooks: List[str]
    caption_hook: str
    caption_body: str
    cta: str
    hashtags: List[str]
