"""Bounded, atomic credits awarded only on a real authentication event."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select

from backend.app.core.database import Database
from backend.app.db.models import DbCreditPromotionCampaign, DbCreditPromotionClaim
from backend.app.services.points import PointsStore, make_idempotency_id

BETA_LOGIN_CAMPAIGN_ID = "beta_first_20_logins_v1"
BETA_LOGIN_MAX_CLAIMS = 20
BETA_LOGIN_CREDIT_AMOUNT = 30
BETA_LOGIN_TRANSACTION_REASON = "beta_login_credit"

LoginPromotionStatus = Literal[
    "disabled",
    "awarded",
    "already_claimed",
    "exhausted",
]


class LoginPromotionConfigurationError(RuntimeError):
    """Raised when an enabled campaign does not match its reviewed contract."""


@dataclass(frozen=True, slots=True)
class LoginPromotionClaimResult:
    status: LoginPromotionStatus
    awarded_credits: int
    slot_number: int | None


class LoginPromotionStore:
    """Serialize campaign claims and credit the wallet in one DB transaction."""

    def __init__(
        self,
        db: Database,
        *,
        campaign_id: str = BETA_LOGIN_CAMPAIGN_ID,
        points_store: PointsStore | None = None,
    ) -> None:
        self.db = db
        self.campaign_id = campaign_id
        self.points_store = points_store or PointsStore(db=db)

    def claim_for_login(
        self,
        user_id: str,
        *,
        enabled: bool,
    ) -> LoginPromotionClaimResult:
        """Award at most one slot to this user and never exceed the global cap."""
        if not enabled:
            return LoginPromotionClaimResult(
                status="disabled",
                awarded_credits=0,
                slot_number=None,
            )
        if not user_id:
            raise LoginPromotionConfigurationError("A login promotion claim requires a user")

        now = int(time.time())
        with self.db.session() as session:
            # Every claimant takes the same row lock first. This makes the
            # check, ordinal allocation, ledger credit and counter increment a
            # single global ordering even across multiple backend processes.
            campaign = session.scalar(
                select(DbCreditPromotionCampaign)
                .where(DbCreditPromotionCampaign.id == self.campaign_id)
                .with_for_update()
                .limit(1)
            )
            if campaign is None:
                raise LoginPromotionConfigurationError("The enabled login promotion is missing")
            self._assert_campaign_contract(campaign)

            existing = session.get(
                DbCreditPromotionClaim,
                (self.campaign_id, user_id),
            )
            if existing is not None:
                return LoginPromotionClaimResult(
                    status="already_claimed",
                    awarded_credits=0,
                    slot_number=int(existing.slot_number),
                )

            if int(campaign.claimed_count) >= int(campaign.max_claims):
                return LoginPromotionClaimResult(
                    status="exhausted",
                    awarded_credits=0,
                    slot_number=None,
                )

            slot_number = int(campaign.claimed_count) + 1
            amount = int(campaign.credit_amount)
            transaction_id = make_idempotency_id(
                "credit_promotion",
                self.campaign_id,
                user_id,
            )
            _, applied = self.points_store.credit_once_in_session(
                session,
                user_id,
                amount,
                reason=BETA_LOGIN_TRANSACTION_REASON,
                transaction_id=transaction_id,
                meta={
                    "campaign_id": self.campaign_id,
                    "slot_number": slot_number,
                    "max_claims": int(campaign.max_claims),
                    "credit_amount": amount,
                    "funding": "operator_sponsored_cloud",
                },
                # These credits must work with the real cloud transcription
                # path, while the transaction reason keeps them distinct from
                # a customer purchase or billing record.
                paid_credit_delta=amount,
            )
            if not applied:
                raise LoginPromotionConfigurationError(
                    "A promotion ledger entry exists without its campaign claim",
                )

            # Materialize the ledger row before the claim's explicit foreign
            # key is inserted. Both writes still share this outer transaction,
            # so a later failure rolls the wallet and transaction back too.
            session.flush()

            session.add(
                DbCreditPromotionClaim(
                    campaign_id=self.campaign_id,
                    user_id=user_id,
                    slot_number=slot_number,
                    credit_amount=amount,
                    point_transaction_id=transaction_id,
                    claimed_at=now,
                )
            )
            campaign.claimed_count = slot_number
            session.flush()

            return LoginPromotionClaimResult(
                status="awarded",
                awarded_credits=amount,
                slot_number=slot_number,
            )

    @staticmethod
    def _assert_campaign_contract(campaign: DbCreditPromotionCampaign) -> None:
        if (
            int(campaign.max_claims) != BETA_LOGIN_MAX_CLAIMS
            or int(campaign.credit_amount) != BETA_LOGIN_CREDIT_AMOUNT
            or int(campaign.claimed_count) < 0
            or int(campaign.claimed_count) > BETA_LOGIN_MAX_CLAIMS
        ):
            raise LoginPromotionConfigurationError(
                "The login promotion does not match the reviewed 20-by-30 contract",
            )
