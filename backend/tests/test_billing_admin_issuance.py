from __future__ import annotations

from backend.tests.billing_admin_test_support import (
    Database,
    DbBillingInvoice,
    DbCreditPurchase,
    TestClient,
    ThreadPoolExecutor,
    _allow_billing_admin,
    _assert_sensitive_admin_response_is_not_cacheable,
    _auth_headers,
    _issued_payload,
    _seed_pending_invoice,
    _set_purchase_reversal_state,
    cast,
    financial_retention_deadline,
    pytest,
    text,
    time,
    uuid,
)


def test_admin_records_already_issued_aade_document_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, original_retention = _seed_pending_invoice(
        user_id=user_id,
    )
    issued_at = int(time.time()) - 30
    payload = _issued_payload(issued_at=issued_at)

    request_started_at = int(time.time())
    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    request_finished_at = int(time.time())

    assert response.status_code == 200, response.text
    # REGRESSION: The write response contains AADE/payment identifiers and
    # needs the same cache prohibition as the snapshot listing.
    _assert_sensitive_admin_response_is_not_cacheable(response)
    response_body = response.json()
    recorded_at = response_body["recorded_at"]
    assert request_started_at <= recorded_at <= request_finished_at
    expected_retention = max(
        financial_retention_deadline(issued_at),
        financial_retention_deadline(recorded_at),
    )
    assert response_body == {
        "invoice_id": invoice_id,
        "purchase_id": purchase_id,
        "document_status": "issued",
        "aade_document_type": payload["document_type"],
        "aade_series": payload["series"],
        "aade_aa": payload["aa"],
        "aade_mark": payload["mark"],
        "issued_at": issued_at,
        "recorded_at": recorded_at,
        "financial_retention_until": expected_retention,
    }
    assert response_body["financial_retention_until"] > original_retention

    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_retention
        assert invoice.financial_retention_until == expected_retention
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at == recorded_at


def test_record_issued_waits_on_purchase_without_locking_invoice(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    db = Database()

    # REGRESSION: reversal/cleanup writers hold the purchase before touching
    # the invoice. While one does so, the admin writer must wait on that parent
    # without first taking the child lock, or the two transactions can deadlock.
    with db.engine.connect() as blocker:
        transaction = blocker.begin()
        blocker_pid = blocker.execute(
            text("SELECT pg_backend_pid()"),
        ).scalar_one()
        blocker.execute(
            text(
                """
                SELECT id
                FROM credit_purchases
                WHERE id = :purchase_id
                FOR UPDATE
                """
            ),
            {"purchase_id": purchase_id},
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(
                client.post,
                f"/billing/admin/invoices/{invoice_id}/record-issued",
                headers=headers,
                json=payload,
            )
            waiting_on_parent = False
            deadline = time.monotonic() + 10
            try:
                while time.monotonic() < deadline:
                    with db.engine.connect() as observer:
                        waiting_on_parent = bool(
                            observer.execute(
                                text(
                                    """
                                    SELECT EXISTS (
                                        SELECT 1
                                        FROM pg_stat_activity AS activity
                                        WHERE :blocker_pid = ANY(
                                            pg_blocking_pids(activity.pid)
                                        )
                                          AND activity.query ILIKE
                                              '%credit_purchases%'
                                    )
                                    """
                                ),
                                {"blocker_pid": blocker_pid},
                            ).scalar_one()
                        )
                    if waiting_on_parent or request.done():
                        break
                    time.sleep(0.05)
                assert waiting_on_parent, "Admin writer did not serialize on the locked purchase"
                # This succeeds only if the waiting admin transaction has not
                # already taken the child row lock.
                blocker.execute(
                    text(
                        """
                        SELECT id
                        FROM billing_invoices
                        WHERE id = :invoice_id
                        FOR UPDATE NOWAIT
                        """
                    ),
                    {"invoice_id": invoice_id},
                )
            finally:
                transaction.rollback()

            response = request.result(timeout=10)

    assert response.status_code == 200, response.text
    assert response.json()["document_status"] == "issued"


@pytest.mark.parametrize(
    "reversal_state",
    (
        {
            "status": "partially_refunded",
            "refunded_amount_cents": 25,
            "reversed_amount_cents": 25,
            "reversed_credits": 25,
        },
        {
            "status": "paid",
            "reversed_amount_cents": 25,
        },
        {
            "status": "disputed",
            "reversed_amount_cents": 100,
            "reversed_credits": 100,
            "dispute_active": True,
        },
        {
            "status": "paid",
            "reversed_credits": 25,
        },
    ),
)
def test_record_issued_blocks_active_or_inconsistent_reversal_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    reversal_state: dict[str, str | int | bool],
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status=cast(str, reversal_state["status"]),
        refunded_amount_cents=cast(
            int,
            reversal_state.get("refunded_amount_cents", 0),
        ),
        reversed_amount_cents=cast(
            int,
            reversal_state.get("reversed_amount_cents", 0),
        ),
        reversed_credits=cast(
            int,
            reversal_state.get("reversed_credits", 0),
        ),
        dispute_active=cast(
            bool,
            reversal_state.get("dispute_active", False),
        ),
    )

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=_issued_payload(issued_at=int(time.time()) - 30),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Purchase requires reversal accounting review before recording an AADE document"
    )
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_document_type is None
        assert invoice.aade_series is None
        assert invoice.aade_aa is None
        assert invoice.aade_mark is None
        assert invoice.issued_at is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None


def test_record_issued_exact_replay_returns_existing_without_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    replay_headers, replay_user_id = _auth_headers(
        client,
        email=f"billing-admin-replay-{uuid.uuid4().hex}@example.com",
    )
    monkeypatch.setenv(
        "GSP_BILLING_ADMIN_USER_IDS",
        f"{user_id},{replay_user_id}",
    )
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200

    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at is not None
        expected_recorded_by_user_id = invoice.recorded_by_user_id
        expected_recorded_at = invoice.recorded_at
        purchase.financial_retention_until += 172_800
        invoice.financial_retention_until += 86_400
        purchase.updated_at -= 19
        invoice.updated_at -= 17
        expected_purchase_retention = purchase.financial_retention_until
        expected_invoice_retention = invoice.financial_retention_until
        expected_purchase_updated_at = purchase.updated_at
        expected_invoice_updated_at = invoice.updated_at

    replay = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=replay_headers,
        json=payload,
    )

    # REGRESSION: A successful write whose HTTP response was lost must be
    # recoverable by replaying the exact immutable AADE identity.
    assert replay.status_code == 200, replay.text
    _assert_sensitive_admin_response_is_not_cacheable(replay)
    assert replay.json() == {
        "invoice_id": invoice_id,
        "purchase_id": purchase_id,
        "document_status": "issued",
        "aade_document_type": payload["document_type"],
        "aade_series": payload["series"],
        "aade_aa": payload["aa"],
        "aade_mark": payload["mark"],
        "issued_at": payload["issued_at"],
        "recorded_at": expected_recorded_at,
        "financial_retention_until": expected_invoice_retention,
    }
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_purchase_retention
        assert invoice.financial_retention_until == expected_invoice_retention
        assert purchase.updated_at == expected_purchase_updated_at
        assert invoice.updated_at == expected_invoice_updated_at
        assert invoice.recorded_by_user_id == expected_recorded_by_user_id
        assert invoice.recorded_at == expected_recorded_at


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("document_type", "1.1"),
        ("series", "A"),
        ("aa", "999999"),
        ("mark", "9223372036854775807"),
        ("issued_at", 1_600_000_001),
    ),
)
def test_record_issued_mismatched_replay_is_conflict_and_does_not_overwrite(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str | int,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    first_payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=first_payload,
    )
    assert first.status_code == 200
    replay_payload = dict(first_payload)
    replay_payload[field] = replacement

    replay = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=replay_payload,
    )

    assert replay.status_code == 409
    assert replay.json()["detail"] == "AADE document has already been recorded"
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.aade_document_type == first_payload["document_type"]
        assert invoice.aade_series == first_payload["series"]
        assert invoice.aade_aa == first_payload["aa"]
        assert invoice.aade_mark == first_payload["mark"]
        assert invoice.issued_at == first_payload["issued_at"]
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at == first.json()["recorded_at"]


def test_record_issued_exact_replay_does_not_bypass_reversal_review(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    first = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200
    _set_purchase_reversal_state(
        purchase_id=purchase_id,
        status="disputed",
        reversed_amount_cents=100,
        reversed_credits=100,
        dispute_active=True,
    )
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        expected_purchase_retention = purchase.financial_retention_until
        expected_invoice_retention = invoice.financial_retention_until
        expected_purchase_updated_at = purchase.updated_at
        expected_invoice_updated_at = invoice.updated_at

    replay = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert replay.status_code == 409
    assert replay.json()["detail"] == ("Purchase requires reversal accounting review before recording an AADE document")
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_purchase_retention
        assert invoice.financial_retention_until == expected_invoice_retention
        assert purchase.updated_at == expected_purchase_updated_at
        assert invoice.updated_at == expected_invoice_updated_at


def test_record_issued_rejects_incomplete_identity_without_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    _, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    incomplete = _issued_payload(issued_at=int(time.time()) - 30)
    incomplete.pop("mark")

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=incomplete,
    )

    assert response.status_code == 422
    db = Database()
    with db.session() as session:
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert invoice is not None
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_mark is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("document_type", "1.1"),
        ("series", "A"),
    ),
)
def test_record_issued_rejects_non_mizai_accounting_baseline_without_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str,
) -> None:
    email = f"billing-admin-{uuid.uuid4().hex}@example.com"
    headers, user_id = _auth_headers(client, email=email)
    _allow_billing_admin(monkeypatch, user_id)
    purchase_id, invoice_id, _ = _seed_pending_invoice(user_id=user_id)
    payload = _issued_payload(issued_at=int(time.time()) - 30)
    payload[field] = replacement
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        expected_purchase_retention = purchase.financial_retention_until
        expected_invoice_retention = invoice.financial_retention_until
        expected_purchase_updated_at = purchase.updated_at
        expected_invoice_updated_at = invoice.updated_at

    response = client.post(
        f"/billing/admin/invoices/{invoice_id}/record-issued",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ("AADE document type and series must match the approved Greek B2C baseline")
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.financial_retention_until == expected_purchase_retention
        assert invoice.financial_retention_until == expected_invoice_retention
        assert purchase.updated_at == expected_purchase_updated_at
        assert invoice.updated_at == expected_invoice_updated_at
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_document_type is None
        assert invoice.aade_series is None
        assert invoice.aade_aa is None
        assert invoice.aade_mark is None
        assert invoice.issued_at is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None
