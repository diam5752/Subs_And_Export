"""Tests for the versioned, fail-closed consumer-contract registry."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.services import consumer_contracts as consumer_contract_module
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    ConsumerContractValidationError,
    assert_consumer_contract_registry_approved,
    build_consumer_contract_snapshot,
    consumer_contract_registry_is_approved,
    consumer_contract_snapshot_sha256,
    public_consumer_contract,
)


def _acceptance(locale: str = "el") -> ConsumerContractAcceptance:
    disclosure = public_consumer_contract(locale)
    return ConsumerContractAcceptance(
        catalog_version="catalog-v1",
        disclosure_id=str(disclosure["disclosure_id"]),
        disclosure_sha256=str(disclosure["disclosure_sha256"]),
        locale=locale,  # type: ignore[arg-type]
        policy_version=str(disclosure["policy_version"]),
        terms_version=str(disclosure["terms_version"]),
        withdrawal_notice_version=str(disclosure["withdrawal_notice_version"]),
        terms_accepted=True,
        immediate_performance_requested=True,
        withdrawal_consequences_acknowledged=True,
    )


def test_registry_is_localized_versioned_and_content_addressed() -> None:
    greek = public_consumer_contract("el")
    english = public_consumer_contract("en")

    assert greek["status"] == "approved"
    assert greek["classification"] == "digital_service_with_prepaid_internal_units"
    assert greek["disclosure_id"] != english["disclosure_id"]
    assert greek["disclosure_sha256"] != english["disclosure_sha256"]
    assert len(str(greek["disclosure_sha256"])) == 64
    assert "14" in str(greek["content"]["withdrawal_notice"])
    assert "downloadable" in str(greek["content"]["credit_description"])
    assert "επιλέξιμο μέσο πληρωμής προεγκρίνεται προσωρινά" in str(
        greek["content"]["purchase_terms"],
    )
    assert "authorization is canceled" in str(
        english["content"]["purchase_terms"],
    )
    assert greek["launch_review_status"]["adjustment_workflow"] == "approved"
    assert greek["launch_review_status"]["adjustment_workflow_implemented"] is True
    assert greek["trader"]["legal_name"] == "Ascentia G.P."
    assert greek["trader"]["legal_form"] == "General Partnership (O.E.)"
    assert greek["trader"]["tax_identification_number"] == "802523620"
    assert greek["trader"]["vat_id"] == "EL802523620"
    assert greek["trader"]["commercial_registration_number"] == "177974203000"
    assert greek["trader"]["euid"] == "ELGEMI.177974203000"
    assert greek["trader"]["country"] == "GR"
    assert consumer_contract_registry_is_approved() is True


def test_backend_and_frontend_share_one_approved_publication_identity() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    backend_identity_path = repository_root / "backend/app/services/paid_credit_legal_publication.json"
    frontend_identity_path = repository_root / "frontend/src/lib/paidCreditLegalPublication.json"

    assert backend_identity_path.read_bytes() == (frontend_identity_path.read_bytes())
    identity = json.loads(backend_identity_path.read_text(encoding="utf-8"))
    assert identity == {
        "approval_identity_sha256": ("652048585a9bc1a3fa6bf6c88768230b1c30052eddff4f07b9190d89a0771f9e"),
        "public_terms_route": "/terms",
        "schema_version": 1,
        "status": "approved",
        "terms_version": "2026-08-28-owner-approved-v2",
    }


def test_registry_approval_fails_closed_after_any_identity_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_consumer_contract_registry_approved()
    approved_manifest = consumer_contract_module.CONSUMER_CONTRACT_APPROVAL_MANIFEST
    monkeypatch.setattr(
        consumer_contract_module,
        "ADJUSTMENT_WORKFLOW_IMPLEMENTED",
        False,
    )
    assert consumer_contract_registry_is_approved() is False
    with pytest.raises(RuntimeError, match="not approved in code"):
        assert_consumer_contract_registry_approved()

    tampered_manifest = {
        **approved_manifest,
        "el": {
            **approved_manifest["el"],
            "disclosure_sha256": "0" * 64,
        },
    }
    monkeypatch.setattr(
        consumer_contract_module,
        "ADJUSTMENT_WORKFLOW_IMPLEMENTED",
        True,
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_CONTRACT_APPROVAL_MANIFEST",
        tampered_manifest,
    )
    assert consumer_contract_registry_is_approved() is False

    tampered_publication = {
        **consumer_contract_module.PAID_CREDIT_LEGAL_PUBLICATION_IDENTITY,
        "approval_identity_sha256": "0" * 64,
    }
    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_CONTRACT_APPROVAL_MANIFEST",
        approved_manifest,
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "PAID_CREDIT_LEGAL_PUBLICATION_IDENTITY",
        tampered_publication,
    )
    assert consumer_contract_registry_is_approved() is False


def test_snapshot_records_exact_text_and_server_timestamp() -> None:
    acceptance = _acceptance()

    snapshot = build_consumer_contract_snapshot(
        acceptance,
        expected_catalog_version="catalog-v1",
        accepted_at=1_721_000_000,
    )

    assert snapshot["accepted_at"] == 1_721_000_000
    assert snapshot["catalog_version"] == "catalog-v1"
    assert snapshot["contract_confirmation_delivery"] == {
        "channel": "account_vault",
        "status": "available_approved",
    }
    assert snapshot["acceptances"]["terms"]["accepted"] is True
    assert snapshot["acceptances"]["terms"]["accepted_at"] == 1_721_000_000
    assert len(snapshot["acceptances"]["terms"]["text_sha256"]) == 64
    assert len(consumer_contract_snapshot_sha256(snapshot)) == 64


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("catalog_version", "old-catalog", "catalog version is stale"),
        ("disclosure_id", "old-disclosure", "disclosure is stale"),
        ("disclosure_sha256", "0" * 64, "disclosure is stale"),
        ("policy_version", "old-policy", "disclosure is stale"),
        ("terms_version", "old-terms", "disclosure is stale"),
        ("withdrawal_notice_version", "old-withdrawal", "disclosure is stale"),
        ("terms_accepted", False, "acceptances are required"),
        ("immediate_performance_requested", False, "acceptances are required"),
        ("withdrawal_consequences_acknowledged", False, "acceptances are required"),
        ("terms_accepted", 1, "acceptances are required"),
    ],
)
def test_snapshot_rejects_stale_identity_and_non_strict_acceptance(
    field: str,
    value: object,
    message: str,
) -> None:
    acceptance = replace(_acceptance(), **{field: value})

    with pytest.raises(ConsumerContractValidationError, match=message):
        build_consumer_contract_snapshot(
            acceptance,
            expected_catalog_version="catalog-v1",
            accepted_at=1_721_000_000,
        )


def test_registry_rejects_unknown_locale_and_invalid_server_time() -> None:
    with pytest.raises(ConsumerContractValidationError, match="Unsupported"):
        public_consumer_contract("fr")

    with pytest.raises(ConsumerContractValidationError, match="timestamp"):
        build_consumer_contract_snapshot(
            _acceptance(),
            expected_catalog_version="catalog-v1",
            accepted_at=0,
        )
