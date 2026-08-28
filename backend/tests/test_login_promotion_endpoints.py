from __future__ import annotations

import secrets

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.api import deps
from backend.app.api.endpoints import auth as auth_endpoints
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import DbCreditPromotionCampaign, DbCreditPromotionClaim
from backend.app.services.login_promotion import LoginPromotionStore
from backend.main import app


def _install_test_campaign(client: TestClient, monkeypatch) -> tuple[Database, str]:
    del client
    db = Database()
    campaign_id = f"beta-endpoint-{secrets.token_hex(8)}"
    with db.session() as session:
        session.add(
            DbCreditPromotionCampaign(
                id=campaign_id,
                max_claims=50,
                credit_amount=30,
                claimed_count=0,
                created_at=1_700_000_000,
            )
        )
    monkeypatch.setattr(settings, "beta_login_promotion_enabled", True)
    app.dependency_overrides[deps.get_login_promotion_store] = lambda: LoginPromotionStore(
        db=db,
        campaign_id=campaign_id,
    )
    return db, campaign_id


def test_local_login_awards_beta_credits_only_once(client: TestClient, monkeypatch) -> None:
    db, campaign_id = _install_test_campaign(client, monkeypatch)
    email = f"beta-local-{secrets.token_hex(8)}@example.com"
    password = "testpassword123"
    registration = client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Beta Local"},
    )
    assert registration.status_code == 200

    try:
        first = client.post(
            "/auth/token",
            data={"username": email, "password": password},
        )
        second = client.post(
            "/auth/token",
            data={"username": email, "password": password},
        )
    finally:
        app.dependency_overrides.pop(deps.get_login_promotion_store, None)

    assert first.status_code == 200
    assert first.json()["beta_credits_awarded"] == 30
    assert second.status_code == 200
    assert second.json()["beta_credits_awarded"] == 0

    points = client.get(
        "/auth/points",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    )
    assert points.status_code == 200
    assert points.json() == {
        "balance": 30,
        "paid_balance": 30,
        "promotional_balance": 0,
        "reversal_debt": 0,
        "ai_spendable_balance": 30,
    }
    exported = client.get(
        "/auth/export",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    )
    assert exported.status_code == 200
    assert exported.json()["credit_promotion_claims"] == [
        {
            "campaign_id": campaign_id,
            "slot_number": 1,
            "credit_amount": 30,
            "point_transaction_id": exported.json()["point_transactions"][-1]["id"],
            "claimed_at": exported.json()["credit_promotion_claims"][0]["claimed_at"],
        }
    ]
    with db.session() as session:
        assert session.scalar(
            select(func.count())
            .select_from(DbCreditPromotionClaim)
            .where(DbCreditPromotionClaim.campaign_id == campaign_id)
        ) == 1


def test_google_login_uses_the_same_beta_campaign(client: TestClient, monkeypatch) -> None:
    db, campaign_id = _install_test_campaign(client, monkeypatch)
    suffix = secrets.token_hex(8)
    monkeypatch.setattr(auth_endpoints, "google_client_id", lambda: "google-client")
    monkeypatch.setattr(
        auth_endpoints,
        "verify_google_id_token",
        lambda *_args, **_kwargs: {
            "email": f"beta-google-{suffix}@example.com",
            "name": "Beta Google",
            "sub": f"google-sub-{suffix}",
            "avatar_url": None,
        },
    )

    try:
        response = client.post("/auth/google", json={"id_token": "verified-test-token"})
    finally:
        app.dependency_overrides.pop(deps.get_login_promotion_store, None)

    assert response.status_code == 200
    assert response.json()["beta_credits_awarded"] == 30
    points = client.get(
        "/auth/points",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert points.status_code == 200
    assert points.json()["ai_spendable_balance"] == 30
    with db.session() as session:
        claim = session.scalar(
            select(DbCreditPromotionClaim).where(
                DbCreditPromotionClaim.campaign_id == campaign_id,
            )
        )
        assert claim is not None
        assert claim.slot_number == 1


def test_login_still_succeeds_after_the_fifty_slots_are_exhausted(
    client: TestClient,
    monkeypatch,
) -> None:
    db, campaign_id = _install_test_campaign(client, monkeypatch)
    with db.session() as session:
        campaign = session.get(DbCreditPromotionCampaign, campaign_id)
        assert campaign is not None
        campaign.claimed_count = 50

    email = f"beta-exhausted-{secrets.token_hex(8)}@example.com"
    password = "testpassword123"
    assert client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Later Beta Tester"},
    ).status_code == 200

    try:
        response = client.post(
            "/auth/token",
            data={"username": email, "password": password},
        )
    finally:
        app.dependency_overrides.pop(deps.get_login_promotion_store, None)

    assert response.status_code == 200
    assert response.json()["beta_credits_awarded"] == 0


def test_login_fails_closed_when_an_enabled_grant_cannot_be_recorded(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "beta_login_promotion_enabled", True)
    email = f"beta-failure-{secrets.token_hex(8)}@example.com"
    password = "testpassword123"
    assert client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Beta Failure"},
    ).status_code == 200

    class FailingPromotionStore:
        def claim_for_login(self, *_args, **_kwargs):
            raise RuntimeError("simulated promotion outage")

    app.dependency_overrides[deps.get_login_promotion_store] = FailingPromotionStore
    try:
        response = client.post(
            "/auth/token",
            data={"username": email, "password": password},
        )
    finally:
        app.dependency_overrides.pop(deps.get_login_promotion_store, None)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Sign-in is temporarily unavailable. Please try again.",
    }
