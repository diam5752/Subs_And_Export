"""Shared structural contract for usage-ledger operation mixins."""

from __future__ import annotations

from typing import Any

from backend.app.core.database import Database
from backend.app.services.points import PointsStore
from backend.app.services.provider_budget import ProviderBudgetStore


class UsageLedgerMixinBase:
    db: Database
    points_store: PointsStore
    provider_budget_store: ProviderBudgetStore

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
