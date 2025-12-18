"""Atomic, auditable intelligence points accounting."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..core.database import Database
from ..db.models import DbPointTransaction, DbUserPoints

STARTING_POINTS_BALANCE = 1000

PROCESS_VIDEO_DEFAULT_COST = 200
PROCESS_VIDEO_MODEL_COSTS: dict[str, int] = {
    "ultimate": 500,
}

FACT_CHECK_COST = 100
SOCIAL_COPY_COST = 50
REFUND_REASON_PREFIX = "refund_"


def process_video_cost(transcribe_model: str) -> int:
    normalized = transcribe_model.strip().lower()
    return PROCESS_VIDEO_MODEL_COSTS.get(normalized, PROCESS_VIDEO_DEFAULT_COST)

def refund_reason(original_reason: str) -> str:
    cleaned = original_reason.strip()
    reason = f"{REFUND_REASON_PREFIX}{cleaned}" if cleaned else f"{REFUND_REASON_PREFIX}unknown"
    return reason[:64]

def make_idempotency_id(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


class PointsStore:
    """Service layer that owns all balance mutations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_balance(self, user_id: str) -> int:
        self.ensure_account(user_id)
        with self.db.session() as session:
            balance = session.scalar(
                select(DbUserPoints.balance).where(DbUserPoints.user_id == user_id).limit(1)
            )
            return int(balance or 0)

    def ensure_account(self, user_id: str) -> bool:
        now = int(time.time())
        with self.db.session() as session:
            return self._ensure_account_in_session(session, user_id=user_id, now=now)

    def spend(
        self,
        user_id: str,
        cost: int,
        reason: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        if cost <= 0:
            raise HTTPException(status_code=400, detail="Invalid cost")
        _validate_reason(reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")

        now = int(time.time())
        with self.db.session() as session:
            self._ensure_account_in_session(session, user_id=user_id, now=now)

            result = session.execute(
                update(DbUserPoints)
                .where(DbUserPoints.user_id == user_id, DbUserPoints.balance >= cost)
                .values(
                    balance=DbUserPoints.balance - cost,
                    updated_at=now,
                )
            )
            if int(result.rowcount or 0) != 1:
                raise HTTPException(status_code=402, detail="Insufficient points")

            session.add(
                DbPointTransaction(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    delta=-cost,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )

            new_balance = session.scalar(
                select(DbUserPoints.balance).where(DbUserPoints.user_id == user_id).limit(1)
            )
            return int(new_balance or 0)

    def credit(
        self,
        user_id: str,
        amount: int,
        reason: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")
        _validate_reason(reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")

        now = int(time.time())
        with self.db.session() as session:
            self._ensure_account_in_session(session, user_id=user_id, now=now)

            session.execute(
                update(DbUserPoints)
                .where(DbUserPoints.user_id == user_id)
                .values(
                    balance=DbUserPoints.balance + amount,
                    updated_at=now,
                )
            )
            session.add(
                DbPointTransaction(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    delta=amount,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )
            new_balance = session.scalar(
                select(DbUserPoints.balance).where(DbUserPoints.user_id == user_id).limit(1)
            )
            return int(new_balance or 0)

    def refund(
        self,
        user_id: str,
        amount: int,
        *,
        original_reason: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        return self.credit(user_id, amount, reason=refund_reason(original_reason), meta=meta)

    def refund_once(
        self,
        user_id: str,
        amount: int,
        *,
        original_reason: str,
        transaction_id: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")
        if not transaction_id or len(transaction_id) > 32:
            raise HTTPException(status_code=400, detail="Invalid transaction id")
        _validate_reason(original_reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")

        now = int(time.time())
        with self.db.session() as session:
            self._ensure_account_in_session(session, user_id=user_id, now=now)

            dialect_name = session.get_bind().dialect.name
            insert_stmt = (
                pg_insert(DbPointTransaction)
                if dialect_name == "postgresql"
                else sqlite_insert(DbPointTransaction)
            )
            insert_base = (
                insert_stmt
                .values(
                    id=transaction_id,
                    user_id=user_id,
                    delta=amount,
                    reason=refund_reason(original_reason),
                    meta=meta,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=[DbPointTransaction.id])
            )

            # psycopg (Postgres) may report rowcount=0 even when the row was inserted,
            # so use RETURNING to reliably detect insertion.
            if dialect_name == "postgresql":
                inserted = (
                    session.execute(insert_base.returning(DbPointTransaction.id)).scalar_one_or_none()
                    is not None
                )
            else:
                insert_result = session.execute(insert_base)
                inserted = int(insert_result.rowcount or 0) == 1
            if inserted:
                session.execute(
                    update(DbUserPoints)
                    .where(DbUserPoints.user_id == user_id)
                    .values(
                        balance=DbUserPoints.balance + amount,
                        updated_at=now,
                    )
                )

            new_balance = session.scalar(
                select(DbUserPoints.balance).where(DbUserPoints.user_id == user_id).limit(1)
            )
            return int(new_balance or 0)

    def _ensure_account_in_session(self, session: Session, *, user_id: str, now: int) -> bool:
        dialect_name = session.get_bind().dialect.name
        insert_stmt = (
            pg_insert(DbUserPoints)
            if dialect_name == "postgresql"
            else sqlite_insert(DbUserPoints)
        )
        insert_base = (
            insert_stmt
            .values(
                user_id=user_id,
                balance=STARTING_POINTS_BALANCE,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[DbUserPoints.user_id])
        )
        if dialect_name == "postgresql":
            created = (
                session.execute(insert_base.returning(DbUserPoints.user_id)).scalar_one_or_none()
                is not None
            )
        else:
            result = session.execute(insert_base)
            created = int(result.rowcount or 0) == 1
        if created:
            session.add(
                DbPointTransaction(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    delta=STARTING_POINTS_BALANCE,
                    reason="initial_balance",
                    meta={"source": "ensure_account"},
                    created_at=now,
                )
            )
        return created


def _validate_reason(reason: str) -> None:
    cleaned = reason.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid reason")
    if len(cleaned) > 64:
        raise HTTPException(status_code=400, detail="Invalid reason")
