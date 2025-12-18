from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.core.database import Database
from backend.app.db.models import DbPointTransaction, DbUser, DbUserPoints
from backend.app.services.points import STARTING_POINTS_BALANCE, PointsStore, process_video_cost


def _seed_user(db: Database, *, user_id: str, email: str) -> None:
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=email,
                name="Test",
                provider="local",
                password_hash="x",
                google_sub=None,
                created_at="now",
            )
        )


def test_ensure_account_creates_row_and_initial_transaction(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    user_id = "u1"
    _seed_user(db, user_id=user_id, email="u1@example.com")

    store = PointsStore(db=db)
    created = store.ensure_account(user_id)
    assert created is True
    assert store.get_balance(user_id) == STARTING_POINTS_BALANCE

    created_again = store.ensure_account(user_id)
    assert created_again is False

    with db.session() as session:
        txs = list(
            session.scalars(
                select(DbPointTransaction).where(DbPointTransaction.user_id == user_id)
            ).all()
        )
        assert len(txs) == 1
        assert txs[0].delta == STARTING_POINTS_BALANCE
        assert txs[0].reason == "initial_balance"


def test_spend_deducts_points_and_logs_transaction(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    user_id = "u1"
    _seed_user(db, user_id=user_id, email="u1@example.com")

    store = PointsStore(db=db)
    store.ensure_account(user_id)

    new_balance = store.spend(user_id, 200, reason="process_video", meta={"model": "medium"})
    assert new_balance == STARTING_POINTS_BALANCE - 200

    with db.session() as session:
        points = session.get(DbUserPoints, user_id)
        assert points is not None
        assert points.balance == STARTING_POINTS_BALANCE - 200

        txs = list(
            session.scalars(
                select(DbPointTransaction)
                .where(DbPointTransaction.user_id == user_id)
                .order_by(DbPointTransaction.created_at.asc())
            ).all()
        )
        assert [tx.delta for tx in txs] == [STARTING_POINTS_BALANCE, -200]
        assert txs[-1].reason == "process_video"


def test_spend_insufficient_funds_is_atomic(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    user_id = "u1"
    _seed_user(db, user_id=user_id, email="u1@example.com")

    store = PointsStore(db=db)
    store.ensure_account(user_id)

    with pytest.raises(HTTPException) as exc_info:
        store.spend(user_id, STARTING_POINTS_BALANCE + 1, reason="process_video")

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == "Insufficient points"

    with db.session() as session:
        points = session.get(DbUserPoints, user_id)
        assert points is not None
        assert points.balance == STARTING_POINTS_BALANCE

        tx_count = session.scalar(
            select(func.count())
            .select_from(DbPointTransaction)
            .where(DbPointTransaction.user_id == user_id)
        )
        assert int(tx_count or 0) == 1


def test_process_video_cost_supports_ultimate_alias() -> None:
    assert process_video_cost("turbo") == 200
    assert process_video_cost("ultimate") == 500
