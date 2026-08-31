from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
from threading import Barrier as Barrier
from typing import Any as Any

import pytest as pytest
from sqlalchemy import select as select
from sqlalchemy.orm import Session as Session

from backend.app.core.database import Database
from backend.app.db.models import (
    DbJob,
    DbUser,
)
from backend.app.db.models import (
    DbPointTransaction as DbPointTransaction,
)
from backend.app.db.models import (
    DbProviderBudgetReservation as DbProviderBudgetReservation,
)
from backend.app.db.models import (
    DbUsageLedger as DbUsageLedger,
)
from backend.app.services.points import PointsStore as PointsStore
from backend.app.services.points import make_idempotency_id as make_idempotency_id
from backend.app.services.usage_ledger import UsageLedgerStore as UsageLedgerStore


def _seed_user(db: Database) -> str:
    user_id = uuid.uuid4().hex
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=f"{user_id}@example.com",
                name="Ledger",
                provider="local",
                password_hash="x",
                google_sub=None,
                created_at="now",
            )
        )
    return user_id


def _seed_job(db: Database, user_id: str, job_id: str) -> str:
    now = int(time.time())
    with db.session() as session:
        session.add(
            DbJob(
                id=job_id,
                user_id=user_id,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
    return job_id
