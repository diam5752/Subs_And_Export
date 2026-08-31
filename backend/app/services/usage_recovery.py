"""Failure recovery and stale-reservation reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DbPointTransaction,
    DbProviderBudgetReservation,
    DbUsageLedger,
)
from backend.app.services.points import make_idempotency_id
from backend.app.services.usage_ledger_base import UsageLedgerMixinBase
from backend.app.services.usage_types import ChargeReservation


@dataclass(frozen=True)
class _OrphanDebitEvidence:
    reserve_debit: DbPointTransaction | None
    recovered_ledger_id: str | None
    linked_transactions: list[DbPointTransaction]


class UsageRecoveryMixin(UsageLedgerMixinBase):
    def refund_if_reserved(
        self,
        reservation: ChargeReservation,
        *,
        status: str,
        error: str | None = None,
    ) -> int:
        return cast(int, self.fail(reservation, status=status, error=error))

    def fail_job_reservations(
        self,
        job_id: str,
        *,
        error: str,
        status: str = "failed",
    ) -> int:
        """Compensate every paid step before a stale active job is deleted."""
        with self.db.session() as session:
            ledgers = list(
                session.scalars(
                    select(DbUsageLedger)
                    .where(DbUsageLedger.job_id == job_id)
                    .order_by(
                        DbUsageLedger.created_at.asc(),
                        DbUsageLedger.id.asc(),
                    )
                ).all()
            )
            reservations = [
                self._reservation_from_ledger(
                    ledger,
                    idempotency_key=str(ledger.idempotency_key or ""),
                )
                for ledger in ledgers
                if ledger.idempotency_key
            ]

        settled = 0
        for reservation in reservations:
            self.fail(reservation, status=status, error=error)
            settled += 1
        return settled

    def _stale_reservations(
        self,
        session: Session,
        *,
        stale_before: int,
        limit: int,
    ) -> list[ChargeReservation]:
        ledgers = list(
            session.scalars(
                select(DbUsageLedger)
                .where(
                    DbUsageLedger.status.in_(
                        {
                            "reserved",
                            "dispatched",
                            "finalizing",
                            "failing_refund",
                            "failing_refund_dispatched",
                            "failing_charged",
                        }
                    ),
                    DbUsageLedger.updated_at < stale_before,
                )
                .order_by(
                    DbUsageLedger.updated_at.asc(),
                    DbUsageLedger.id.asc(),
                )
                .limit(limit)
            ).all()
        )
        return [
            self._reservation_from_ledger(
                ledger,
                idempotency_key=str(ledger.idempotency_key or ""),
            )
            for ledger in ledgers
            if ledger.idempotency_key
        ]

    @staticmethod
    def _stale_orphan_budget_keys(
        session: Session,
        *,
        stale_before: int,
        limit: int,
    ) -> list[str]:
        return list(
            session.scalars(
                select(DbProviderBudgetReservation.idempotency_key)
                .outerjoin(
                    DbUsageLedger,
                    DbUsageLedger.idempotency_key == DbProviderBudgetReservation.idempotency_key,
                )
                .where(
                    DbProviderBudgetReservation.status == "reserved",
                    DbProviderBudgetReservation.updated_at < stale_before,
                    DbUsageLedger.id.is_(None),
                )
                .order_by(
                    DbProviderBudgetReservation.updated_at.asc(),
                    DbProviderBudgetReservation.idempotency_key.asc(),
                )
                .limit(limit)
            ).all()
        )

    @staticmethod
    def _ledger_exists(session: Session, idempotency_key: str) -> bool:
        return (
            session.scalar(select(DbUsageLedger.id).where(DbUsageLedger.idempotency_key == idempotency_key).limit(1))
            is not None
        )

    @staticmethod
    def _lock_orphan_debit(
        session: Session,
        idempotency_key: str,
    ) -> _OrphanDebitEvidence:
        reserve_tx_id = make_idempotency_id("reserve", idempotency_key)
        reserve_debit = session.scalar(
            select(DbPointTransaction).where(DbPointTransaction.id == reserve_tx_id).with_for_update().limit(1)
        )
        if reserve_debit is None:
            return _OrphanDebitEvidence(None, None, [])
        if int(reserve_debit.delta) >= 0:
            raise RuntimeError("Orphan usage reserve transaction is not a debit")
        debit_meta = reserve_debit.meta if isinstance(reserve_debit.meta, dict) else {}
        recovered_ledger_id = debit_meta.get("ledger_id")
        if not isinstance(recovered_ledger_id, str) or len(recovered_ledger_id) != 32:
            raise RuntimeError("Orphan usage debit has no recoverable ledger")
        linked_transactions = list(
            session.scalars(
                select(DbPointTransaction)
                .where(
                    DbPointTransaction.user_id == reserve_debit.user_id,
                    or_(
                        DbPointTransaction.id == reserve_tx_id,
                        DbPointTransaction.meta["ledger_id"].as_string() == recovered_ledger_id,
                    ),
                )
                .order_by(DbPointTransaction.id.asc())
                .with_for_update()
            ).all()
        )
        return _OrphanDebitEvidence(
            reserve_debit,
            recovered_ledger_id,
            linked_transactions,
        )

    def _refund_orphan_debit(
        self,
        session: Session,
        evidence: _OrphanDebitEvidence,
    ) -> None:
        reserve_debit = evidence.reserve_debit
        if reserve_debit is None:
            return
        recovered_ledger_id = evidence.recovered_ledger_id
        if recovered_ledger_id is None:
            raise RuntimeError("Orphan usage debit has no recoverable ledger")
        outstanding_charge = max(
            0,
            -sum(int(item.delta) for item in evidence.linked_transactions),
        )
        outstanding_paid_charge = max(
            0,
            -sum(int(item.paid_delta) for item in evidence.linked_transactions),
        )
        if outstanding_paid_charge > outstanding_charge:
            raise RuntimeError("Orphan usage debit has invalid paid allocation")
        if outstanding_charge <= 0:
            return
        refund_tx = make_idempotency_id(
            "refund",
            recovered_ledger_id,
            "stale_orphan",
        )
        self.points_store.refund_once_in_session(
            session,
            reserve_debit.user_id,
            outstanding_charge,
            original_reason=reserve_debit.reason,
            transaction_id=refund_tx,
            meta={
                "ledger_id": recovered_ledger_id,
                "action": reserve_debit.reason,
                "kind": "stale_orphan",
            },
            paid_credit_delta=outstanding_paid_charge,
        )

    def _release_stale_orphan_budget(
        self,
        session: Session,
        *,
        idempotency_key: str,
        stale_before: int,
    ) -> bool:
        orphan = session.scalar(
            select(DbProviderBudgetReservation)
            .where(DbProviderBudgetReservation.idempotency_key == idempotency_key)
            .with_for_update()
            .limit(1)
        )
        if orphan is None or orphan.status != "reserved":
            return False
        if int(orphan.updated_at) >= stale_before:
            return False
        # The budget lock may have waited for a concurrent reserve transaction.
        if self._ledger_exists(session, idempotency_key):
            return False
        self.provider_budget_store.release_in_session(session, idempotency_key)
        return True

    def _reconcile_orphan_budget(
        self,
        session: Session,
        *,
        idempotency_key: str,
        stale_before: int,
    ) -> bool:
        evidence = self._lock_orphan_debit(session, idempotency_key)
        # A concurrent reserve recovery may have recreated the ledger while
        # this stale candidate was waiting on its debit lock.
        if self._ledger_exists(session, idempotency_key):
            return False
        self._refund_orphan_debit(session, evidence)
        return self._release_stale_orphan_budget(
            session,
            idempotency_key=idempotency_key,
            stale_before=stale_before,
        )

    def reconcile_stale_reservations(
        self,
        *,
        stale_before: int,
        limit: int = 100,
    ) -> int:
        """Refund stale provider claims left behind by a crashed worker."""
        if stale_before <= 0:
            raise ValueError("stale_before must be positive")
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.db.session() as session:
            reservations = self._stale_reservations(
                session,
                stale_before=stale_before,
                limit=limit,
            )
            orphan_budget_keys = self._stale_orphan_budget_keys(
                session,
                stale_before=stale_before,
                limit=limit,
            )
            reconciled_orphan_budgets = sum(
                self._reconcile_orphan_budget(
                    session,
                    idempotency_key=idempotency_key,
                    stale_before=stale_before,
                )
                for idempotency_key in orphan_budget_keys
            )

        for reservation in reservations:
            self.fail(
                reservation,
                status="failed",
                error="Stale paid provider dispatch reconciled",
                stale_before=stale_before,
            )
        return len(reservations) + reconciled_orphan_budgets
