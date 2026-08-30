"""Value objects exposed by the usage-ledger facade."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChargeReservation:
    ledger_id: str
    user_id: str
    job_id: str | None
    action: str
    provider: str
    model: str | None
    tier: str | None
    reserved_credits: int
    min_credits: int
    idempotency_key: str
    paid_credits_reserved: int = 0
    estimated_cost_usd: float = 0.0


@dataclass(frozen=True)
class ChargePlan:
    """Charge reservations tied to a processing job."""

    transcription: ChargeReservation | None = None


@dataclass(frozen=True)
class UsageSummaryRow:
    bucket: str
    credits_reserved: int
    credits_charged: int
    cost_usd: float
    count: int
