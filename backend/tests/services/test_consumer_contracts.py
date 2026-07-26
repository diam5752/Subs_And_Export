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

    assert greek["status"] == "draft_unapproved"
    assert greek["classification"] == "digital_service_with_prepaid_internal_units"
    assert greek["disclosure_id"] != english["disclosure_id"]
    assert greek["disclosure_sha256"] != english["disclosure_sha256"]
    assert len(str(greek["disclosure_sha256"])) == 64
    assert "14" in str(greek["content"]["withdrawal_notice"])
    assert "downloadable" in str(greek["content"]["credit_description"])
    assert consumer_contract_registry_is_approved() is False


def test_backend_and_frontend_share_one_fail_closed_publication_identity() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    backend_identity_path = repository_root / "backend/app/services/paid_credit_legal_publication.json"
    frontend_identity_path = repository_root / "frontend/src/lib/paidCreditLegalPublication.json"

    assert backend_identity_path.read_bytes() == (frontend_identity_path.read_bytes())
    identity = json.loads(backend_identity_path.read_text(encoding="utf-8"))
    assert identity == {
        "approval_identity_sha256": None,
        "public_terms_route": "/terms",
        "schema_version": 1,
        "status": "inactive_unapproved",
        "terms_version": "2026-07-26-draft-v1",
    }


def test_registry_approval_requires_reviewed_code_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="not approved in code"):
        assert_consumer_contract_registry_approved()

    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_CONTRACT_STATUS",
        "approved",
    )
    assert consumer_contract_registry_is_approved() is False
    monkeypatch.setattr(
        consumer_contract_module,
        "DURABLE_CONFIRMATION_CHANNEL_STATUS",
        "approved",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "ADJUSTMENT_WORKFLOW_STATUS",
        "approved",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "CONTRACT_CONFIRMATION_DELIVERY_STATUS",
        consumer_contract_module.APPROVED_CONTRACT_CONFIRMATION_DELIVERY_STATUS,
    )
    assert consumer_contract_registry_is_approved() is False

    monkeypatch.setattr(
        consumer_contract_module,
        "ADJUSTMENT_WORKFLOW_IMPLEMENTED",
        True,
    )
    assert consumer_contract_registry_is_approved() is False
    manifest: dict[str, dict[str, str]] = {}
    for locale in ("el", "en"):
        disclosure = public_consumer_contract(locale)
        manifest[locale] = {
            "locale": locale,
            "policy_version": str(disclosure["policy_version"]),
            "terms_version": str(disclosure["terms_version"]),
            "withdrawal_notice_version": str(
                disclosure["withdrawal_notice_version"],
            ),
            "confirmation_template_version": str(
                disclosure["confirmation_template_version"],
            ),
            "disclosure_id": str(disclosure["disclosure_id"]),
            "disclosure_sha256": str(
                disclosure["disclosure_sha256"],
            ),
        }
    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_CONTRACT_APPROVAL_MANIFEST",
        manifest,
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "ADJUSTMENT_WORKFLOW_IMPLEMENTED",
        False,
    )
    assert consumer_contract_registry_is_approved() is False
    monkeypatch.setattr(
        consumer_contract_module,
        "ADJUSTMENT_WORKFLOW_IMPLEMENTED",
        True,
    )
    # Status flips and a matching manifest must never approve wording whose
    # legal/version identity is still explicitly marked as a draft.
    assert consumer_contract_registry_is_approved() is False

    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_POLICY_VERSION",
        "2026-07-26-reviewed-v1",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "TERMS_VERSION",
        "2026-07-26-reviewed-v1",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "WITHDRAWAL_NOTICE_VERSION",
        "2026-07-26-reviewed-v1",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "CONFIRMATION_TEMPLATE_VERSION",
        "2026-07-26-reviewed-v1",
    )
    monkeypatch.setattr(
        consumer_contract_module,
        "_DISCLOSURES",
        tuple(
            replace(
                disclosure,
                disclosure_id=disclosure.disclosure_id.replace(
                    "-draft-v1",
                    "-reviewed-v1",
                ),
            )
            for disclosure in consumer_contract_module._DISCLOSURES
        ),
    )
    reviewed_manifest: dict[str, dict[str, str]] = {}
    for locale in ("el", "en"):
        disclosure = public_consumer_contract(locale)
        reviewed_manifest[locale] = {
            "locale": locale,
            "policy_version": str(disclosure["policy_version"]),
            "terms_version": str(disclosure["terms_version"]),
            "withdrawal_notice_version": str(
                disclosure["withdrawal_notice_version"],
            ),
            "confirmation_template_version": str(
                disclosure["confirmation_template_version"],
            ),
            "disclosure_id": str(disclosure["disclosure_id"]),
            "disclosure_sha256": str(
                disclosure["disclosure_sha256"],
            ),
        }
    monkeypatch.setattr(
        consumer_contract_module,
        "CONSUMER_CONTRACT_APPROVAL_MANIFEST",
        reviewed_manifest,
    )
    assert consumer_contract_registry_is_approved() is False
    monkeypatch.setattr(
        consumer_contract_module,
        "PAID_CREDIT_LEGAL_PUBLICATION_IDENTITY",
        {
            "schema_version": 1,
            "status": "approved",
            "public_terms_route": "/terms",
            "terms_version": "2026-07-26-reviewed-v1",
            "approval_identity_sha256": (consumer_contract_module.paid_credit_legal_publication_approval_sha256()),
        },
    )
    assert consumer_contract_registry_is_approved() is True
    assert_consumer_contract_registry_approved()

    reviewed_manifest["el"] = {
        **reviewed_manifest["el"],
        "disclosure_sha256": "0" * 64,
    }
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
        "status": "available_pending_external_approval",
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
