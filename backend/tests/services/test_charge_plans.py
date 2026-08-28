"""Unit tests for charge reservation helpers."""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.app.core import config
from backend.app.core.database import Database
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.db.models import DbJob, DbUser
from backend.app.services import pricing
from backend.app.services.charge_plans import (
    assert_external_provider_budget,
    preflight_processing_charges,
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
        assert reservation.min_credits == 25
        assert reservation.reserved_credits == 25
        assert balance == starting_balance - 25

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
        assert reservation.reserved_credits == 25
        assert balance == starting_balance - 25


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
        assert charge_plan.transcription.reserved_credits == 25
        assert charge_plan.social_copy.reserved_credits == 0
        assert balance == starting_balance - 25

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
        assert balance == starting_balance - 25


def test_processing_preflight_rejects_zero_credit_without_reserving() -> None:
    db = Database()
    user_id = _seed_user(db)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reserve = MagicMock(wraps=ledger_store.reserve)
    budget_reserve = MagicMock(
        wraps=ledger_store.provider_budget_store.reserve_in_session,
    )
    ledger_store.reserve = reserve  # type: ignore[method-assign]
    ledger_store.provider_budget_store.reserve_in_session = budget_reserve  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        preflight_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=False,
            llm_model="gpt-5-mini",
            provider="local",
            stt_model=config.settings.transcribe_tier_model["standard"],
        )

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == "Insufficient points"
    assert points_store.get_balance(user_id) == 0
    reserve.assert_not_called()
    budget_reserve.assert_not_called()


def test_processing_preflight_preserves_external_provider_paid_credit_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id, starting_balance_override=100)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reserve = MagicMock(wraps=ledger_store.reserve)
    monkeypatch.setattr(ledger_store, "reserve", reserve)
    monkeypatch.setattr(config.settings, "mock_external_services", False)

    with pytest.raises(HTTPException) as exc_info:
        preflight_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=False,
            llm_model="gpt-5-mini",
            provider="groq",
            stt_model="whisper-large-v3-turbo",
        )

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == "Insufficient paid credits"
    assert points_store.get_balances(user_id).promotional_balance == 100
    assert points_store.get_balances(user_id).paid_balance == 0
    reserve.assert_not_called()


def test_processing_preflight_rejects_closed_budget_before_wallet_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    wallet_check = MagicMock()
    monkeypatch.setattr(points_store, "assert_can_spend", wallet_check)
    monkeypatch.setattr(config.settings, "mock_external_services", False)
    monkeypatch.setattr(config.settings, "external_provider_monthly_budget_usd", 0.0)
    monkeypatch.setattr(config.settings, "external_provider_daily_budget_usd", 0.0)
    monkeypatch.setattr(config.settings, "external_provider_per_request_budget_usd", 1.0)
    monkeypatch.setattr(pricing, "stt_provider_cost_usd", lambda **_kwargs: 0.01)

    with pytest.raises(ProviderBudgetExceededError, match="closed"):
        preflight_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=False,
            llm_model="gpt-5-mini",
            provider="elevenlabs",
            stt_model="scribe_v2",
        )

    wallet_check.assert_not_called()

class TestExternalProviderBudget:
    """The app budget is enforced before any provider reservation."""

    class _Ledger:
        def __init__(self, spent: float) -> None:
            self.spent = spent
            # ``assert_can_reserve`` is a real ProviderBudgetStore method; allow
            # that name instead of treating it as a misspelled mock assertion.
            self.provider_budget_store = MagicMock(unsafe=True)

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

    def test_current_window_preflight_uses_guarded_estimate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ledger = self._Ledger(0.0)
        monkeypatch.setattr(config.settings, "external_provider_monthly_budget_usd", 2.0)
        monkeypatch.setattr(config.settings, "external_provider_daily_budget_usd", 1.0)
        monkeypatch.setattr(config.settings, "external_provider_per_request_budget_usd", 0.5)
        monkeypatch.setattr(config.settings, "external_provider_price_safety_multiplier", 1.25)

        assert_external_provider_budget(
            ledger_store=ledger,  # type: ignore[arg-type]
            estimated_cost_usd=0.2,
        )

        ledger.provider_budget_store.assert_can_reserve.assert_called_once_with(
            estimated_usd=pytest.approx(0.25),
            daily_limit_usd=1.0,
            monthly_limit_usd=2.0,
        )

    @pytest.mark.parametrize("estimate", [-0.01, float("nan"), float("inf")])
    def test_invalid_provider_estimate_fails_closed(self, estimate: float) -> None:
        with pytest.raises(ProviderBudgetExceededError, match="Invalid"):
            assert_external_provider_budget(
                ledger_store=self._Ledger(0.0),  # type: ignore[arg-type]
                estimated_cost_usd=estimate,
            )


def test_processing_charge_fails_before_reservation_when_economics_are_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: an allowed provider budget must still fail closed before any
    # paid-credit reservation when the guarded contribution margin is unsafe.
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-economics-{uuid.uuid4().hex[:8]}"
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
    monkeypatch.setattr(
        pricing,
        "stt_provider_cost_usd",
        lambda **_kwargs: 0.20,
    )

    with pytest.raises(ProviderBudgetExceededError, match="economics guard"):
        reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=False,
            llm_model="gpt-5-mini",
            provider="elevenlabs",
            stt_model="scribe_v2",
        )

    assert points_store.get_balance(user_id) == starting_balance
