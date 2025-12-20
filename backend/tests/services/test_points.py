from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.core.database import Database
from backend.app.db.models import DbPointTransaction, DbUser, DbUserPoints
from backend.app.services.points import (
    STARTING_POINTS_BALANCE,
    PointsStore,
    make_idempotency_id,
)


def _seed_user(db: Database, *, user_id: str | None = None, email: str | None = None) -> str:
    resolved_user_id = user_id or uuid.uuid4().hex
    resolved_email = email or f"{resolved_user_id}@example.com"
    with db.session() as session:
        session.add(
            DbUser(
                id=resolved_user_id,
                email=resolved_email,
                name="Test",
                provider="local",
                password_hash="x",
                google_sub=None,
                created_at="now",
            )
        )
    return resolved_user_id


def test_ensure_account_creates_row_and_initial_transaction(tmp_path: Path) -> None:
    db = Database()
    user_id = _seed_user(db)

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
    db = Database()
    user_id = _seed_user(db)

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


def test_spend_once_is_idempotent(tmp_path: Path) -> None:
    # REGRESSION: spend_once must only deduct once for the same transaction id.
    db = Database()
    user_id = _seed_user(db)

    store = PointsStore(db=db)
    store.ensure_account(user_id)

    balance, spent = store.spend_once(
        user_id,
        100,
        reason="process_video",
        transaction_id="a" * 32,
        meta={"job_id": "j1"},
    )
    assert spent is True
    assert balance == STARTING_POINTS_BALANCE - 100

    balance_again, spent_again = store.spend_once(
        user_id,
        100,
        reason="process_video",
        transaction_id="a" * 32,
        meta={"job_id": "j1"},
    )
    assert spent_again is False
    assert balance_again == STARTING_POINTS_BALANCE - 100

    with db.session() as session:
        txs = list(
            session.scalars(
                select(DbPointTransaction)
                .where(DbPointTransaction.user_id == user_id)
                .order_by(DbPointTransaction.created_at.asc())
            ).all()
        )
        assert [tx.delta for tx in txs] == [STARTING_POINTS_BALANCE, -100]


def test_spend_insufficient_funds_is_atomic(tmp_path: Path) -> None:
    db = Database()
    user_id = _seed_user(db)

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


def test_spend_rejects_invalid_inputs(tmp_path: Path) -> None:
    db = Database()
    user_id = _seed_user(db)

    store = PointsStore(db=db)

    with pytest.raises(HTTPException) as exc_info:
        store.spend(user_id, 0, reason="process_video")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid cost"

    with pytest.raises(HTTPException) as exc_info:
        store.spend(user_id, 1, reason="process_video", meta="nope")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid meta"

    with pytest.raises(HTTPException) as exc_info:
        store.spend(user_id, 1, reason=" ")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid reason"

    with pytest.raises(HTTPException) as exc_info:
        store.spend(user_id, 1, reason="x" * 65)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid reason"


def test_credit_and_refund_log_transactions(tmp_path: Path) -> None:
    db = Database()
    user_id = _seed_user(db)

    store = PointsStore(db=db)
    store.ensure_account(user_id)

    credited = store.credit(user_id, 250, reason="purchase", meta={"source": "test"})
    assert credited == STARTING_POINTS_BALANCE + 250

    refunded = store.refund(user_id, 250, original_reason="purchase", meta={"source": "test"})
    assert refunded == STARTING_POINTS_BALANCE + 500

    with db.session() as session:
        txs = list(
            session.scalars(
                select(DbPointTransaction)
                .where(DbPointTransaction.user_id == user_id)
                .order_by(DbPointTransaction.created_at.asc())
            ).all()
        )
        assert [tx.delta for tx in txs] == [STARTING_POINTS_BALANCE, 250, 250]
        assert txs[-1].reason == "refund_purchase"


def test_credit_rejects_invalid_inputs(tmp_path: Path) -> None:
    db = Database()
    user_id = _seed_user(db)

    store = PointsStore(db=db)

    with pytest.raises(HTTPException) as exc_info:
        store.credit(user_id, 0, reason="purchase")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid amount"

    with pytest.raises(HTTPException) as exc_info:
        store.credit(user_id, 1, reason="purchase", meta="nope")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid meta"


def test_refund_once_rejects_invalid_inputs(tmp_path: Path) -> None:
    db = Database()
    user_id = _seed_user(db)

    store = PointsStore(db=db)
    store.ensure_account(user_id)

    with pytest.raises(HTTPException) as exc_info:
        store.refund_once(user_id, 0, original_reason="process_video", transaction_id="a" * 32)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid amount"

    with pytest.raises(HTTPException) as exc_info:
        store.refund_once(user_id, 1, original_reason="process_video", transaction_id="")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid transaction id"

    with pytest.raises(HTTPException) as exc_info:
        store.refund_once(user_id, 1, original_reason="process_video", transaction_id="a" * 33)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid transaction id"

    with pytest.raises(HTTPException) as exc_info:
        store.refund_once(
            user_id,
            1,
            original_reason="process_video",
            transaction_id="a" * 32,
            meta="nope",  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid meta"


def test_ensure_account_in_session_postgres_branch_is_covered(tmp_path: Path) -> None:
    store = PointsStore(db=Database())
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"

    created_result = MagicMock()
    created_result.scalar_one_or_none.return_value = "u1"
    session.execute.return_value = created_result

    created = store._ensure_account_in_session(session, user_id="u1", now=123)
    assert created is True
    session.add.assert_called_once()

    session.reset_mock()
    not_created_result = MagicMock()
    not_created_result.scalar_one_or_none.return_value = None
    session.execute.return_value = not_created_result

    created = store._ensure_account_in_session(session, user_id="u1", now=123)
    assert created is False
    session.add.assert_not_called()


def test_refund_once_postgres_branch_uses_returning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = PointsStore(db=Database())
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"
    session.scalar.return_value = 900

    insert_exec_result = MagicMock()
    insert_exec_result.scalar_one_or_none.return_value = "txid"
    session.execute.side_effect = [insert_exec_result, MagicMock()]

    monkeypatch.setattr(store, "_ensure_account_in_session", lambda *_args, **_kwargs: False)

    @contextmanager
    def _session() -> object:
        yield session

    monkeypatch.setattr(store.db, "session", _session)

    balance = store.refund_once(
        "u1",
        100,
        original_reason="process_video",
        transaction_id="a" * 32,
        meta={"job_id": "j1"},
    )
    assert balance == 900
    assert session.execute.call_count >= 1


def test_refund_once_credits_balance_and_is_idempotent(tmp_path: Path) -> None:
    # REGRESSION: refund_once must credit the balance exactly once (even if called repeatedly).
    db = Database()
    user_id = _seed_user(db)

    store = PointsStore(db=db)
    store.ensure_account(user_id)

    store.spend(user_id, 200, reason="process_video", meta={"job_id": "j1"})

    tx_id = make_idempotency_id("refund", user_id, "process_video", "j1", "200")
    refunded = store.refund_once(
        user_id,
        200,
        original_reason="process_video",
        transaction_id=tx_id,
        meta={"job_id": "j1"},
    )
    assert refunded == STARTING_POINTS_BALANCE

    refunded_again = store.refund_once(
        user_id,
        200,
        original_reason="process_video",
        transaction_id=tx_id,
        meta={"job_id": "j1"},
    )
    assert refunded_again == STARTING_POINTS_BALANCE

    with db.session() as session:
        points = session.get(DbUserPoints, user_id)
        assert points is not None
        assert points.balance == STARTING_POINTS_BALANCE

        txs = list(
            session.scalars(
                select(DbPointTransaction)
                .where(DbPointTransaction.user_id == user_id)
                .order_by(DbPointTransaction.created_at.asc())
            ).all()
        )
        assert [tx.delta for tx in txs] == [STARTING_POINTS_BALANCE, -200, 200]
        assert txs[-1].id == tx_id
        assert txs[-1].reason == "refund_process_video"



