from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_credit_catalog_is_public_and_checkout_requires_login(client: TestClient) -> None:
    catalog = client.get("/billing/catalog")
    assert catalog.status_code == 200
    assert [item["credits"] for item in catalog.json()["video_pricing"]] == [30, 60, 100]

    checkout = client.post(
        "/billing/checkout",
        headers={"Idempotency-Key": f"checkout-{uuid.uuid4().hex}"},
        json={"package_key": "starter"},
    )
    assert checkout.status_code == 401


def test_checkout_fails_closed_until_owner_enables_stripe(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    checkout = client.post(
        "/billing/checkout",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"checkout-{uuid.uuid4().hex}",
        },
        json={"package_key": "starter"},
    )
    assert checkout.status_code == 503
    assert checkout.json()["detail"] == "Credit purchases are not enabled yet"


def test_points_endpoint_exposes_paid_and_promotional_balances(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = client.get("/auth/points", headers=user_auth_headers)
    assert response.status_code == 200
    assert response.json() == {
        "balance": 100,
        "paid_balance": 0,
        "promotional_balance": 100,
        "reversal_debt": 0,
        "ai_spendable_balance": 0,
    }
