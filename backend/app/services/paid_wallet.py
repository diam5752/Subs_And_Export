"""Paid-wallet purchase, reversal, and restoration mutations."""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.core.database import Database
from backend.app.db.models import DbPointTransaction, DbUserPoints


@dataclass(frozen=True, slots=True)
class PaidWalletMutation:
    balance: int
    paid_balance: int
    reversal_debt: int
    credit_delta: int
    debt_delta: int
    applied: bool


class PaidWalletMixin:
    """Transaction-preserving paid-wallet behavior mixed into PointsStore."""

    db: Database

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

    def apply_paid_purchase_once_in_session(
        self,
        session: Session,
        user_id: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> PaidWalletMutation:
        """Credit a paid purchase inside the caller's accounting transaction."""
        return self._mutate_paid_wallet_once_in_session(
            session=session,
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

    def reverse_paid_purchase_once_in_session(
        self,
        session: Session,
        user_id: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> PaidWalletMutation:
        """Apply a reversal inside the caller's accounting transaction."""
        return self._mutate_paid_wallet_once_in_session(
            session=session,
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

    def restore_paid_reversal_once_in_session(
        self,
        session: Session,
        user_id: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> PaidWalletMutation:
        """Restore a reversal inside the caller's accounting transaction."""
        return self._mutate_paid_wallet_once_in_session(
            session=session,
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
        with self.db.session() as session:
            return self._mutate_paid_wallet_once_in_session(
                session=session,
                user_id=user_id,
                amount=amount,
                purchase_id=purchase_id,
                transaction_id=transaction_id,
                operation=operation,
            )

    def _mutate_paid_wallet_once_in_session(
        self,
        *,
        session: Session,
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
        self._ensure_account_in_session(
            session,
            user_id=user_id,
            now=now,
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
        starting_balance_override: int | None = None,
    ) -> bool:
        raise NotImplementedError

    @staticmethod
    def _locked_wallet(session: Session, user_id: str) -> DbUserPoints:
        raise NotImplementedError

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
        raise NotImplementedError
