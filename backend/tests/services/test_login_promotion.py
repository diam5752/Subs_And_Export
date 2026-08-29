from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.db.models import (
    DbCreditPromotionCampaign,
    DbCreditPromotionClaim,
    DbPointTransaction,
    DbUserPoints,
)
from backend.app.services.login_promotion import (
    BETA_LOGIN_CAMPAIGN_ID,
    BETA_LOGIN_CREDIT_AMOUNT,
    BETA_LOGIN_MAX_CLAIMS,
    LoginPromotionConfigurationError,
    LoginPromotionStore,
)


def _campaign_id() -> str:
    return f"beta-test-{secrets.token_hex(8)}"


def _create_campaign(
    db: Database,
    campaign_id: str,
    *,
    claimed_count: int = 0,
) -> None:
    with db.session() as session:
        session.add(
            DbCreditPromotionCampaign(
                id=campaign_id,
                max_claims=BETA_LOGIN_MAX_CLAIMS,
                credit_amount=BETA_LOGIN_CREDIT_AMOUNT,
                claimed_count=claimed_count,
                created_at=1_700_000_000,
            )
        )


def _create_users(db: Database, count: int) -> list[str]:
    store = UserStore(db)
    return [
        store.register_local_user(
            email=f"beta-{secrets.token_hex(8)}@example.com",
            password="testpassword123",
            name=f"Beta Tester {index}",
        ).id
        for index in range(count)
    ]


def test_beta_login_campaign_migration_seeds_the_reviewed_contract() -> None:
    db = Database()

    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, BETA_LOGIN_CAMPAIGN_ID)
        assert campaign is not None
        assert campaign.max_claims == 20
        assert campaign.credit_amount == 30
        assert campaign.claimed_count == 0


def test_login_promotion_is_idempotent_and_cloud_spendable() -> None:
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id)
    user_id = _create_users(db, 1)[0]
    store = LoginPromotionStore(db=db, campaign_id=campaign_id)

    first = store.claim_for_login(user_id, enabled=True)
    second = store.claim_for_login(user_id, enabled=True)

    assert first.status == "awarded"
    assert first.awarded_credits == 30
    assert first.slot_number == 1
    assert second.status == "already_claimed"
    assert second.awarded_credits == 0
    assert second.slot_number == 1

    with db.session() as session:
        wallet = session.get(DbUserPoints, user_id)
        assert wallet is not None
        assert wallet.balance == 30
        assert wallet.paid_balance == 30
        assert session.scalar(
            select(func.count())
            .select_from(DbCreditPromotionClaim)
            .where(DbCreditPromotionClaim.campaign_id == campaign_id)
        ) == 1
        transaction = session.scalar(
            select(DbPointTransaction).where(
                DbPointTransaction.user_id == user_id,
                DbPointTransaction.reason == "beta_login_credit",
            )
        )
        assert transaction is not None
        assert transaction.delta == 30
        assert transaction.paid_delta == 30
        assert transaction.meta == {
            "campaign_id": campaign_id,
            "slot_number": 1,
            "max_claims": 20,
            "credit_amount": 30,
            "funding": "operator_sponsored_cloud",
        }


def test_login_promotion_caps_twenty_simultaneous_unique_claims() -> None:
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id)
    user_ids = _create_users(db, BETA_LOGIN_MAX_CLAIMS + 1)

    def claim(user_id: str):
        return LoginPromotionStore(db=db, campaign_id=campaign_id).claim_for_login(
            user_id,
            enabled=True,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(claim, user_ids))

    awarded = [result for result in results if result.status == "awarded"]
    exhausted = [result for result in results if result.status == "exhausted"]
    assert len(awarded) == 20
    assert len(exhausted) == 1
    assert sum(result.awarded_credits for result in results) == 600
    assert sorted(result.slot_number for result in awarded) == list(range(1, 21))

    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        assert campaign is not None
        assert campaign.claimed_count == 20
        claims = list(
            session.scalars(
                select(DbCreditPromotionClaim)
                .where(DbCreditPromotionClaim.campaign_id == campaign_id)
                .order_by(DbCreditPromotionClaim.slot_number.asc())
            ).all()
        )
        assert [claim.slot_number for claim in claims] == list(range(1, 21))
        assert session.scalar(
            select(func.sum(DbPointTransaction.delta)).where(
                DbPointTransaction.reason == "beta_login_credit",
                DbPointTransaction.meta["campaign_id"].as_string() == campaign_id,
            )
        ) == 600


def test_campaign_is_exhausted_after_the_twentieth_slot() -> None:
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id, claimed_count=20)
    user_id = _create_users(db, 1)[0]

    result = LoginPromotionStore(db=db, campaign_id=campaign_id).claim_for_login(
        user_id,
        enabled=True,
    )

    assert result.status == "exhausted"
    assert result.slot_number is None
    assert result.awarded_credits == 0
    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        assert campaign is not None
        assert campaign.claimed_count == 20


def test_login_promotion_is_disabled_without_mutating_the_campaign() -> None:
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id)
    user_id = _create_users(db, 1)[0]

    result = LoginPromotionStore(db=db, campaign_id=campaign_id).claim_for_login(
        user_id,
        enabled=False,
    )

    assert result.status == "disabled"
    assert result.awarded_credits == 0
    assert result.slot_number is None
    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        wallet = session.get(DbUserPoints, user_id)
        assert campaign is not None
        assert wallet is not None
        assert campaign.claimed_count == 0
        assert wallet.balance == 0
        assert wallet.paid_balance == 0


def test_login_promotion_rejects_an_empty_user_or_missing_campaign() -> None:
    db = Database()

    with pytest.raises(LoginPromotionConfigurationError, match="requires a user"):
        LoginPromotionStore(db=db, campaign_id=_campaign_id()).claim_for_login(
            "",
            enabled=True,
        )

    user_id = _create_users(db, 1)[0]
    with pytest.raises(LoginPromotionConfigurationError, match="promotion is missing"):
        LoginPromotionStore(db=db, campaign_id=_campaign_id()).claim_for_login(
            user_id,
            enabled=True,
        )


def test_login_promotion_rejects_a_campaign_contract_mismatch() -> None:
    db = Database()
    campaign_id = _campaign_id()
    with db.session() as session:
        session.add(
            DbCreditPromotionCampaign(
                id=campaign_id,
                max_claims=49,
                credit_amount=30,
                claimed_count=0,
                created_at=1_700_000_000,
            )
        )
    user_id = _create_users(db, 1)[0]

    with pytest.raises(LoginPromotionConfigurationError, match="20-by-30"):
        LoginPromotionStore(db=db, campaign_id=campaign_id).claim_for_login(
            user_id,
            enabled=True,
        )


def test_deleted_account_does_not_reopen_an_awarded_campaign_slot() -> None:
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id)
    first_user_id, second_user_id = _create_users(db, 2)
    store = LoginPromotionStore(db=db, campaign_id=campaign_id)

    first = store.claim_for_login(first_user_id, enabled=True)
    assert first.slot_number == 1
    UserStore(db).delete_user(first_user_id)
    second = store.claim_for_login(second_user_id, enabled=True)

    assert second.status == "awarded"
    assert second.slot_number == 2
    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        assert campaign is not None
        assert campaign.claimed_count == 2
        assert session.get(
            DbCreditPromotionClaim,
            (campaign_id, first_user_id),
        ) is None
        assert session.scalar(
            select(func.count())
            .select_from(DbCreditPromotionClaim)
            .where(DbCreditPromotionClaim.campaign_id == campaign_id)
        ) == 1


def test_login_promotion_rolls_back_counter_and_claim_when_crediting_fails() -> None:
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id)
    user_id = _create_users(db, 1)[0]

    class FailingPointsStore:
        def credit_once_in_session(self, *args, **kwargs):
            raise RuntimeError("simulated ledger failure")

    store = LoginPromotionStore(
        db=db,
        campaign_id=campaign_id,
        points_store=FailingPointsStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="simulated ledger failure"):
        store.claim_for_login(user_id, enabled=True)

    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        wallet = session.get(DbUserPoints, user_id)
        assert campaign is not None
        assert wallet is not None
        assert campaign.claimed_count == 0
        assert wallet.balance == 0
        assert wallet.paid_balance == 0
        assert session.scalar(
            select(func.count())
            .select_from(DbCreditPromotionClaim)
            .where(DbCreditPromotionClaim.campaign_id == campaign_id)
        ) == 0


def test_login_promotion_rejects_an_orphaned_idempotency_entry() -> None:
    # REGRESSION: a pre-existing promotion ledger row without the matching
    # campaign claim must fail closed instead of consuming another slot.
    db = Database()
    campaign_id = _campaign_id()
    _create_campaign(db, campaign_id)
    user_id = _create_users(db, 1)[0]

    class DuplicatePointsStore:
        def credit_once_in_session(self, *args, **kwargs):
            return 30, False

    store = LoginPromotionStore(
        db=db,
        campaign_id=campaign_id,
        points_store=DuplicatePointsStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(LoginPromotionConfigurationError, match="without its campaign claim"):
        store.claim_for_login(user_id, enabled=True)

    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        assert campaign is not None
        assert campaign.claimed_count == 0
        assert session.get(DbCreditPromotionClaim, (campaign_id, user_id)) is None
