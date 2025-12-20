from __future__ import annotations

from pydantic import BaseModel


class UsageSummaryRow(BaseModel):
    bucket: str
    credits_reserved: int
    credits_charged: int
    cost_usd: float
    count: int


class UsageSummaryResponse(BaseModel):
    group_by: str
    start_ts: int
    end_ts: int
    items: list[UsageSummaryRow]
