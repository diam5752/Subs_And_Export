from typing import Optional, Dict
from pydantic import BaseModel

class JobResponse(BaseModel):
    id: str
    status: str
    progress: int
    message: Optional[str]
    created_at: int
    updated_at: int
    result_data: Optional[Dict]
