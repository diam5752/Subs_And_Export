"""Unit tests for charge reservation helpers."""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.app.core import config
from backend.app.core.database import Database
from backend.app.db.models import DbJob, DbUser
from backend.app.services import pricing
from backend.app.services.charge_plans import (
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
        assert reservation.min_credits == config.CREDITS_MIN_TRANSCRIBE["standard"]
        # 2 minutes at 10 credits/min = 20, but min is 25
        assert reservation.reserved_credits == 25
        assert balance == starting_balance - 25

    def test_reserve_pro_tier(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-trans-pro-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
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
        # 3 minutes at 20 credits/min = 60
        assert reservation.reserved_credits == 60
        assert balance == starting_balance - 60


class TestReserveLlmCharge:
    """Test reserve_llm_charge helper."""

    def test_reserve_social_copy_charge(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-llm-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        starting_balance = points_store.get_balance(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        reservation, balance = reserve_llm_charge(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            action="social_copy",
            model="gpt-5.1-mini",
            max_prompt_chars=config.MAX_LLM_INPUT_CHARS,
            max_completion_tokens=config.MAX_LLM_OUTPUT_TOKENS_SOCIAL,
            min_credits=config.CREDITS_MIN_SOCIAL_COPY["standard"],
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
            stt_model=config.GROQ_MODEL_STANDARD,
        )

        assert charge_plan.transcription is not None
        assert charge_plan.social_copy is not None
        assert charge_plan.transcription.action == "transcription"
        assert charge_plan.social_copy.action == "social_copy"

    def test_reserve_without_llm(self) -> None:
        db = Database()
        user_id = _seed_user(db)
        job_id = f"job-proc-nollm-{uuid.uuid4().hex[:8]}"
        _seed_job(db, user_id, job_id)
        points_store = PointsStore(db=db)
        points_store.ensure_account(user_id)
        ledger_store = UsageLedgerStore(db=db, points_store=points_store)

        charge_plan, balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier="standard",
            duration_seconds=60.0,
            use_llm=False,
            llm_model="gpt-5.1-mini",
            provider="groq",
            stt_model=config.GROQ_MODEL_STANDARD,
        )

        assert charge_plan.transcription is not None
        assert charge_plan.social_copy is None
        # Only transcription charge
        assert balance == starting_balance - 25  # min credits
