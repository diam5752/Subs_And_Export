"""Atomic, auditable intelligence points accounting."""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import DbPointTransaction, DbUser, DbUserPoints

STARTING_POINTS_BALANCE = 500
TRIAL_CREDITS = 100  # Credits for unverified users (enough for one basic operation)
VERIFIED_BONUS_CREDITS = 400  # Additional credits after email verification

PROCESS_VIDEO_DEFAULT_COST = settings.credits_min_transcribe["standard"]
PROCESS_VIDEO_MODEL_COSTS: dict[str, int] = {
    "standard": settings.credits_min_transcribe["standard"],
    "pro": settings.credits_min_transcribe["pro"],
}

REFUND_REASON_PREFIX = "refund_"


@dataclass(frozen=True, slots=True)
class PointsBalance:
    balance: int
    paid_balance: int
    reversal_debt: int

    @property
    def promotional_balance(self) -> int:
        return max(0, self.balance - self.paid_balance)

    @property
    def ai_spendable_balance(self) -> int:
        return 0 if self.reversal_debt > 0 else self.paid_balance


@dataclass(frozen=True, slots=True)
class PaidWalletMutation:
    balance: int
    paid_balance: int
    reversal_debt: int
    credit_delta: int
    debt_delta: int
    applied: bool


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
        return self.get_balances(user_id).balance

    def get_balances(self, user_id: str) -> PointsBalance:
        self.ensure_account(user_id)
        with self.db.session() as session:
            wallet = session.scalar(
                select(DbUserPoints).where(DbUserPoints.user_id == user_id).limit(1)
            )
            if wallet is None:
                raise RuntimeError("Points wallet could not be loaded")
            return PointsBalance(
                balance=int(wallet.balance or 0),
                paid_balance=int(wallet.paid_balance or 0),
                reversal_debt=int(wallet.reversal_debt or 0),
            )

    def ensure_account(
        self,
        user_id: str,
        *,
        email_verified: bool | None = None,
        starting_balance_override: int | None = None,
    ) -> bool:
        if starting_balance_override is not None and starting_balance_override < 0:
            raise HTTPException(status_code=400, detail="Invalid starting balance")
        now = int(time.time())
        with self.db.session() as session:
            resolved_email_verified = self._resolve_email_verified(session, user_id, email_verified)
            return self._ensure_account_in_session(
                session,
                user_id=user_id,
                now=now,
                email_verified=resolved_email_verified,
                starting_balance_override=starting_balance_override,
            )

    def spend(
        self,
        user_id: str,
        cost: int,
        reason: str,
        meta: dict[str, Any] | None = None,
        *,
        require_paid: bool = False,
    ) -> int:
        if cost <= 0:
            raise HTTPException(status_code=400, detail="Invalid cost")
        _validate_reason(reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")

        now = int(time.time())
        with self.db.session() as session:
            resolved_email_verified = self._resolve_email_verified(session, user_id, None)
            self._ensure_account_in_session(session, user_id=user_id, now=now, email_verified=resolved_email_verified)
            wallet = self._locked_wallet(session, user_id)
            paid_spend = self._spend_locked_wallet(
                wallet,
                cost=cost,
                now=now,
                require_paid=require_paid,
            )

            session.add(
                DbPointTransaction(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    delta=-cost,
                    paid_delta=-paid_spend,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )
            return int(wallet.balance)

    def spend_once(
        self,
        user_id: str,
        cost: int,
        *,
        reason: str,
        transaction_id: str,
        meta: dict[str, Any] | None = None,
        require_paid: bool = False,
    ) -> tuple[int, bool]:
        if cost <= 0:
            raise HTTPException(status_code=400, detail="Invalid cost")
        if not transaction_id or len(transaction_id) > 32:
            raise HTTPException(status_code=400, detail="Invalid transaction id")
        _validate_reason(reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")

        now = int(time.time())
        with self.db.session() as session:
            resolved_email_verified = self._resolve_email_verified(session, user_id, None)
            self._ensure_account_in_session(session, user_id=user_id, now=now, email_verified=resolved_email_verified)
            existing = session.get(DbPointTransaction, transaction_id)
            if existing is not None:
                self._validate_existing_transaction(
                    existing,
                    user_id=user_id,
                    expected_delta=-cost,
                    reason=reason,
                    expected_paid_delta=-cost if require_paid else None,
                )
                wallet = self._locked_wallet(session, user_id)
                return int(wallet.balance), False

            wallet = self._locked_wallet(session, user_id)
            existing = session.get(DbPointTransaction, transaction_id)
            if existing is not None:
                self._validate_existing_transaction(
                    existing,
                    user_id=user_id,
                    expected_delta=-cost,
                    reason=reason,
                    expected_paid_delta=-cost if require_paid else None,
                )
                return int(wallet.balance), False

            paid_spend = self._spend_locked_wallet(
                wallet,
                cost=cost,
                now=now,
                require_paid=require_paid,
            )
            session.add(
                DbPointTransaction(
                    id=transaction_id,
                    user_id=user_id,
                    delta=-cost,
                    paid_delta=-paid_spend,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )
            return int(wallet.balance), True

    def credit(
        self,
        user_id: str,
        amount: int,
        reason: str,
        meta: dict[str, Any] | None = None,
        *,
        paid_credit_delta: int = 0,
    ) -> int:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")
        _validate_reason(reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")
        _validate_paid_credit_delta(amount, paid_credit_delta)

        now = int(time.time())
        with self.db.session() as session:
            resolved_email_verified = self._resolve_email_verified(session, user_id, None)
            self._ensure_account_in_session(session, user_id=user_id, now=now, email_verified=resolved_email_verified)
            wallet = self._locked_wallet(session, user_id)
            wallet.balance += amount
            wallet.paid_balance += paid_credit_delta
            wallet.updated_at = now
            session.add(
                DbPointTransaction(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    delta=amount,
                    paid_delta=paid_credit_delta,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )
            return int(wallet.balance)

    def credit_once(
        self,
        user_id: str,
        amount: int,
        *,
        reason: str,
        transaction_id: str,
        meta: dict[str, Any] | None = None,
        paid_credit_delta: int = 0,
    ) -> tuple[int, bool]:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")
        if not transaction_id or len(transaction_id) > 32:
            raise HTTPException(status_code=400, detail="Invalid transaction id")
        _validate_reason(reason)
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail="Invalid meta")
        _validate_paid_credit_delta(amount, paid_credit_delta)

        now = int(time.time())
        with self.db.session() as session:
            resolved_email_verified = self._resolve_email_verified(session, user_id, None)
            self._ensure_account_in_session(
                session,
                user_id=user_id,
                now=now,
                email_verified=resolved_email_verified,
            )
            existing = session.get(DbPointTransaction, transaction_id)
            if existing is not None:
                self._validate_existing_transaction(
                    existing,
                    user_id=user_id,
                    expected_delta=amount,
                    reason=reason,
                    expected_paid_delta=paid_credit_delta,
                )
                wallet = self._locked_wallet(session, user_id)
                return int(wallet.balance), False

            wallet = self._locked_wallet(session, user_id)
            existing = session.get(DbPointTransaction, transaction_id)
            if existing is not None:
                self._validate_existing_transaction(
                    existing,
                    user_id=user_id,
                    expected_delta=amount,
                    reason=reason,
                    expected_paid_delta=paid_credit_delta,
                )
                return int(wallet.balance), False

            wallet.balance += amount
            wallet.paid_balance += paid_credit_delta
            wallet.updated_at = now
            session.add(
                DbPointTransaction(
                    id=transaction_id,
                    user_id=user_id,
                    delta=amount,
                    paid_delta=paid_credit_delta,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )
            return int(wallet.balance), True

    def refund(
        self,
        user_id: str,
        amount: int,
        *,
        original_reason: str,
        meta: dict[str, Any] | None = None,
        paid_credit_delta: int = 0,
    ) -> int:
        return self.credit(
            user_id,
            amount,
            reason=refund_reason(original_reason),
            meta=meta,
            paid_credit_delta=paid_credit_delta,
        )

    def refund_once(
        self,
        user_id: str,
        amount: int,
        *,
        original_reason: str,
        transaction_id: str,
        meta: dict[str, Any] | None = None,
        paid_credit_delta: int = 0,
    ) -> int:
        balance, _ = self.credit_once(
            user_id,
            amount,
            reason=refund_reason(original_reason),
            transaction_id=transaction_id,
            meta=meta,
            paid_credit_delta=paid_credit_delta,
        )
        return balance

    def apply_paid_purchase_once(
        self,
        user_id: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> PaidWalletMutation:
        """Credit a paid purchase once, first extinguishing reversal debt."""
        return self._mutate_paid_wallet_once(
            user_id=user_id,
            amount=amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
            operation="purchase",
        )

    def reverse_paid_purchase_once(
        self,
        user_id: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> PaidWalletMutation:
        """Claw back refundable paid credits and turn spent credits into debt."""
        return self._mutate_paid_wallet_once(
            user_id=user_id,
            amount=amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
            operation="reversal",
        )

    def restore_paid_reversal_once(
        self,
        user_id: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> PaidWalletMutation:
        """Restore credits after a refund cancellation or won dispute."""
        return self._mutate_paid_wallet_once(
            user_id=user_id,
            amount=amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
            operation="restore",
        )

    def _mutate_paid_wallet_once(
        self,
        *,
        user_id: str,
        amount: int,
        purchase_id: str,
        transaction_id: str,
        operation: str,
    ) -> PaidWalletMutation:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")
        if not purchase_id or len(purchase_id) > 32:
            raise HTTPException(status_code=400, detail="Invalid purchase id")
        if not transaction_id or len(transaction_id) > 32:
            raise HTTPException(status_code=400, detail="Invalid transaction id")
        if operation not in {"purchase", "reversal", "restore"}:
            raise ValueError("Invalid paid wallet operation")

        reason = {
            "purchase": "stripe_purchase",
            "reversal": "stripe_reversal",
            "restore": "stripe_reversal_restore",
        }[operation]
        now = int(time.time())
        with self.db.session() as session:
            resolved_email_verified = self._resolve_email_verified(session, user_id, None)
            self._ensure_account_in_session(
                session,
                user_id=user_id,
                now=now,
                email_verified=resolved_email_verified,
            )
            existing = session.get(DbPointTransaction, transaction_id)
            if existing is not None:
                return self._existing_paid_wallet_mutation(
                    session,
                    existing,
                    user_id=user_id,
                    purchase_id=purchase_id,
                    operation=operation,
                    amount=amount,
                )

            wallet = self._locked_wallet(session, user_id)
            existing = session.get(DbPointTransaction, transaction_id)
            if existing is not None:
                return self._existing_paid_wallet_mutation(
                    session,
                    existing,
                    user_id=user_id,
                    purchase_id=purchase_id,
                    operation=operation,
                    amount=amount,
                )

            if operation == "purchase":
                debt_repaid = min(amount, int(wallet.reversal_debt))
                credit_delta = amount - debt_repaid
                debt_delta = -debt_repaid
            elif operation == "reversal":
                available = min(amount, int(wallet.paid_balance))
                credit_delta = -available
                debt_delta = amount - available
            else:
                debt_relief = min(amount, int(wallet.reversal_debt))
                credit_delta = amount - debt_relief
                debt_delta = -debt_relief

            wallet.balance += credit_delta
            wallet.paid_balance += credit_delta
            wallet.reversal_debt += debt_delta
            wallet.updated_at = now
            meta = {
                "purchase_id": purchase_id,
                "operation": operation,
                "requested_credits": amount,
                "credit_delta": credit_delta,
                "debt_delta": debt_delta,
            }
            session.add(
                DbPointTransaction(
                    id=transaction_id,
                    user_id=user_id,
                    delta=credit_delta,
                    paid_delta=credit_delta,
                    reversal_debt_delta=debt_delta,
                    reason=reason,
                    meta=meta,
                    created_at=now,
                )
            )
            return PaidWalletMutation(
                balance=int(wallet.balance),
                paid_balance=int(wallet.paid_balance),
                reversal_debt=int(wallet.reversal_debt),
                credit_delta=credit_delta,
                debt_delta=debt_delta,
                applied=True,
            )

    def _ensure_account_in_session(
        self,
        session: Session,
        *,
        user_id: str,
        now: int,
        email_verified: bool,
        starting_balance_override: int | None = None,
    ) -> bool:
        """Create user points account if it doesn't exist.

        Args:
            session: DB session
            user_id: User ID
            now: Unix timestamp
            email_verified: If True, grant full starting credits. If False, grant trial credits only.
            starting_balance_override: Optional override for starting credits (can be zero).
        """
        if starting_balance_override is not None:
            starting_balance = starting_balance_override
            reason = "initial_balance_override"
        else:
            starting_balance = STARTING_POINTS_BALANCE if email_verified else TRIAL_CREDITS
            reason = "initial_balance" if email_verified else "trial_balance"

        insert_stmt = pg_insert(DbUserPoints).values(
            user_id=user_id,
            balance=starting_balance,
            paid_balance=0,
            reversal_debt=0,
            updated_at=now,
        ).on_conflict_do_nothing(index_elements=[DbUserPoints.user_id])

        # Use RETURNING to reliably detect insertion
        created = (
            session.execute(insert_stmt.returning(DbUserPoints.user_id)).scalar_one_or_none()
            is not None
        )

        if created and starting_balance > 0:
            session.add(
                DbPointTransaction(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    delta=starting_balance,
                    paid_delta=0,
                    reason=reason,
                    meta={"source": "ensure_account", "email_verified": email_verified},
                    created_at=now,
                )
            )
        return created

    def grant_verified_credits(self, user_id: str) -> int:
        """Grant bonus credits after email verification.

        This should be called when a user verifies their email to give them
        the remaining credits they would have gotten if they were verified at signup.

        Returns the new balance.
        """
        return self.credit(
            user_id,
            VERIFIED_BONUS_CREDITS,
            reason="email_verified_bonus",
            meta={"source": "email_verification"},
        )

    def _resolve_email_verified(
        self,
        session: Session,
        user_id: str,
        email_verified: bool | None,
    ) -> bool:
        if email_verified is not None:
            return email_verified
        stored_verified = session.scalar(
            select(DbUser.email_verified).where(DbUser.id == user_id).limit(1)
        )
        return bool(stored_verified)

    @staticmethod
    def _locked_wallet(session: Session, user_id: str) -> DbUserPoints:
        wallet = session.scalar(
            select(DbUserPoints)
            .where(DbUserPoints.user_id == user_id)
            .with_for_update()
            .limit(1)
        )
        if wallet is None:
            raise RuntimeError("Points wallet could not be locked")
        return wallet

    @staticmethod
    def _spend_locked_wallet(
        wallet: DbUserPoints,
        *,
        cost: int,
        now: int,
        require_paid: bool,
    ) -> int:
        if require_paid and int(wallet.reversal_debt) > 0:
            raise HTTPException(status_code=402, detail="Outstanding credit reversal")
        if int(wallet.balance) < cost:
            raise HTTPException(status_code=402, detail="Insufficient points")

        promotional_balance = max(0, int(wallet.balance) - int(wallet.paid_balance))
        paid_spend = cost if require_paid else max(0, cost - promotional_balance)
        if int(wallet.paid_balance) < paid_spend:
            detail = "Insufficient paid credits" if require_paid else "Insufficient points"
            raise HTTPException(status_code=402, detail=detail)

        wallet.balance -= cost
        wallet.paid_balance -= paid_spend
        wallet.updated_at = now
        return paid_spend

    @staticmethod
    def _validate_existing_transaction(
        transaction: DbPointTransaction,
        *,
        user_id: str,
        expected_delta: int,
        reason: str,
        expected_paid_delta: int | None = None,
    ) -> None:
        if (
            transaction.user_id != user_id
            or int(transaction.delta) != expected_delta
            or transaction.reason != reason
            or (
                expected_paid_delta is not None
                and int(transaction.paid_delta) != expected_paid_delta
            )
        ):
            raise HTTPException(status_code=409, detail="Idempotency key conflict")

    @staticmethod
    def _existing_paid_wallet_mutation(
        session: Session,
        transaction: DbPointTransaction,
        *,
        user_id: str,
        purchase_id: str,
        operation: str,
        amount: int,
    ) -> PaidWalletMutation:
        meta = transaction.meta if isinstance(transaction.meta, dict) else {}
        if (
            transaction.user_id != user_id
            or meta.get("purchase_id") != purchase_id
            or meta.get("operation") != operation
            or meta.get("requested_credits") != amount
        ):
            raise HTTPException(status_code=409, detail="Idempotency key conflict")
        wallet = PointsStore._locked_wallet(session, user_id)
        return PaidWalletMutation(
            balance=int(wallet.balance),
            paid_balance=int(wallet.paid_balance),
            reversal_debt=int(wallet.reversal_debt),
            credit_delta=int(transaction.delta),
            debt_delta=int(transaction.reversal_debt_delta),
            applied=False,
        )


def _validate_reason(reason: str) -> None:
    cleaned = reason.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid reason")
    if len(cleaned) > 64:
        raise HTTPException(status_code=400, detail="Invalid reason")


def _validate_paid_credit_delta(amount: int, paid_credit_delta: int) -> None:
    if (
        isinstance(paid_credit_delta, bool)
        or not isinstance(paid_credit_delta, int)
        or paid_credit_delta < 0
        or paid_credit_delta > amount
    ):
        raise HTTPException(status_code=400, detail="Invalid paid credit delta")
