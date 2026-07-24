"""Unit tests for charge reservation helpers."""

from __future__ import annotations

import time
import uuid

import pytest

from backend.app.core import config
from backend.app.core.database import Database
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.db.models import DbJob, DbUser
from backend.app.services import pricing
from backend.app.services.charge_plans import (
    assert_external_provider_budget,
    reserve_llm_charge,
    reserve_processing_charges,
    reserve_transcription_charge,
)
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import UsageLedgerStore


def _seed_user(db: Database) -> str:
    user_id = uuid.uuid4().hex
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=f"{user_id}@example.com",
                name="ChargePlan",
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


class TestReserveTranscriptionCharge:
    """Test reserve_transcription_charge helper."""

    def test_reserve_standard_tier(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-trans-std-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        points_store.credit(
            user_id,
            200,
            reason="test_paid_funding",
            paid_credit_delta=200,
        )
        starting_balance = points_store.get_balance(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        reservation, balance = reserve_transcription_charge(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            duration_seconds=120.0,  # 2 minutes
            provider="groq",
            model="whisper-large-v3-turbo",
        )

        assert reservation.action == "transcription"
        assert reservation.tier == "standard"
        assert reservation.provider == "groq"
        assert reservation.min_credits == 30
        assert reservation.reserved_credits == 30
        assert balance == starting_balance - 30

    def test_reserve_pro_tier(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-trans-pro-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        points_store.credit(
            user_id,
            200,
            reason="test_paid_funding",
            paid_credit_delta=200,
        )
        starting_balance = points_store.get_balance(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        reservation, balance = reserve_transcription_charge(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="pro",
            duration_seconds=180.0,  # 3 minutes
            provider="groq",
            model="whisper-large-v3",
        )

        assert reservation.tier == "pro"
        assert reservation.reserved_credits == 30
        assert balance == starting_balance - 30


class TestReserveLlmCharge:
    """Test reserve_llm_charge helper."""

    def test_reserve_social_copy_charge(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-llm-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        points_store.credit(
            user_id,
            200,
            reason="test_paid_funding",
            paid_credit_delta=200,
        )
        starting_balance = points_store.get_balance(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        reservation, balance = reserve_llm_charge(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            action="social_copy",
            model="gpt-5-mini",
            max_prompt_chars=config.settings.max_llm_input_chars,
            max_completion_tokens=config.settings.max_llm_output_tokens_social,
            min_credits=config.settings.credits_min_social_copy["standard"],
        )

        assert reservation.action == "social_copy"
        assert reservation.provider == "openai"
        assert reservation.tier == "standard"
        assert balance < starting_balance


class TestReserveProcessingCharges:
    """Test reserve_processing_charges helper."""

    def test_reserve_with_llm(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-proc-llm-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        points_store.credit(
            user_id,
            200,
            reason="test_paid_funding",
            paid_credit_delta=200,
        )
        starting_balance = points_store.get_balance(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        llm_models = pricing.resolve_llm_models("standard")
        charge_plan, balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=True,
            llm_model=llm_models.social,
            provider="groq",
            stt_model=config.settings.transcribe_tier_model["standard"],
        )

        assert charge_plan.transcription is not None
        assert charge_plan.social_copy is not None
        assert charge_plan.transcription.action == "transcription"
        assert charge_plan.social_copy.action == "social_copy"
        assert charge_plan.transcription.reserved_credits == 30
        assert charge_plan.social_copy.reserved_credits == 0
        assert balance == starting_balance - 30

    def test_reserve_without_llm(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-proc-nollm-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        points_store.credit(
            user_id,
            200,
            reason="test_paid_funding",
            paid_credit_delta=200,
        )
        starting_balance = points_store.get_balance(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        charge_plan, balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=False,
            llm_model="gpt-5-mini",
            provider="groq",
            stt_model=config.settings.transcribe_tier_model["standard"],
        )

        assert charge_plan.transcription is not None
        assert charge_plan.social_copy is None
        # Only transcription charge
        assert balance == starting_balance - 30


class TestExternalProviderBudget:
    """The app budget is enforced before any provider reservation."""

    class _Ledger:
        def __init__(self, spent: float) -> None:
            self.spent = spent

        def total_cost_usd(self, *, start_ts: int, end_ts: int) -> float:
            assert start_ts <= end_ts
            return self.spent

    def test_rejects_closed_monthly_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "external_provider_monthly_budget_usd", 0.0)
        monkeypatch.setattr(config.settings, "external_provider_daily_budget_usd", 1.0)
        monkeypatch.setattr(config.settings, "external_provider_per_request_budget_usd", 0.5)

        with pytest.raises(ProviderBudgetExceededError, match="closed"):
            assert_external_provider_budget(
                ledger_store=self._Ledger(0.9),  # type: ignore[arg-type]
                estimated_cost_usd=0.11,
            )

    def test_rejects_single_expensive_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "external_provider_monthly_budget_usd", 1.0)
        monkeypatch.setattr(config.settings, "external_provider_per_request_budget_usd", 0.25)

        with pytest.raises(ProviderBudgetExceededError, match="Per-request"):
            assert_external_provider_budget(
                ledger_store=self._Ledger(0.0),  # type: ignore[arg-type]
                estimated_cost_usd=0.26,
            )

    def test_local_zero_cost_bypasses_closed_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "external_provider_monthly_budget_usd", 0.0)
        monkeypatch.setattr(config.settings, "external_provider_per_request_budget_usd", 0.0)

        assert_external_provider_budget(
            ledger_store=self._Ledger(100.0),  # type: ignore[arg-type]
            estimated_cost_usd=0.0,
        )
