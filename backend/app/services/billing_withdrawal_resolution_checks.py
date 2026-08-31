"""Pure predicates for immutable withdrawal-resolution records."""

from __future__ import annotations

import hashlib
from collections.abc import Set
from typing import Any, Pattern

from backend.app.db.models import (
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
)


def valid_resolution_links(
    resolution: DbBillingWithdrawalResolution,
    *,
    withdrawal: DbBillingWithdrawalRequest,
    purchase: DbCreditPurchase,
    schema_version: int,
    expected_resolution_id: str,
    expected_reason: str | None,
    expected_adjustment_id: str | None,
) -> bool:
    return (
        resolution.schema_version == schema_version
        and resolution.id == expected_resolution_id
        and resolution.withdrawal_id == withdrawal.id
        and resolution.purchase_id == purchase.id
        and withdrawal.purchase_id == purchase.id
        and resolution.locale == withdrawal.locale
        and expected_reason is not None
        and resolution.reason_code == expected_reason
        and resolution.adjustment_id == expected_adjustment_id
    )


def valid_resolution_explanation(explanation: object) -> bool:
    return isinstance(explanation, str) and explanation.strip() == explanation and 20 <= len(explanation) <= 1_000


def valid_resolution_artifact(
    resolution: DbBillingWithdrawalResolution,
    *,
    purchase: DbCreditPurchase,
    sha256_pattern: Pattern[str],
) -> bool:
    return (
        resolution.resolution_mime_type == "application/json; charset=utf-8"
        and resolution.resolution_filename == f"gsubs-withdrawal-resolution-{purchase.id}.json"
        and isinstance(resolution.resolution_bytes, bytes)
        and sha256_pattern.fullmatch(resolution.resolution_sha256) is not None
        and hashlib.sha256(resolution.resolution_bytes).hexdigest() == resolution.resolution_sha256
    )


def valid_resolution_timestamps(
    resolution: DbBillingWithdrawalResolution,
    *,
    withdrawal: DbBillingWithdrawalRequest,
) -> bool:
    return (
        not isinstance(resolution.resolved_at, bool)
        and resolution.resolved_at >= withdrawal.submitted_at
        and resolution.available_at == resolution.resolved_at
        and resolution.created_at == resolution.resolved_at
        and resolution.financial_retention_until > resolution.resolved_at
    )


def valid_resolution_snapshot_encoding(
    resolution: DbBillingWithdrawalResolution,
    *,
    snapshot: dict[str, Any],
    decoded: object,
    expected_bytes: bytes,
    expected_keys: Set[str],
    schema_version: int,
) -> bool:
    return (
        decoded == snapshot
        and resolution.resolution_bytes == expected_bytes
        and set(snapshot) == expected_keys
        and snapshot.get("schema_version") == schema_version
        and snapshot.get("document_type") == "gsubs_withdrawal_resolution"
    )


def valid_resolution_snapshot_subjects(
    snapshot: dict[str, Any],
    *,
    withdrawal: DbBillingWithdrawalRequest,
    purchase: DbCreditPurchase,
) -> bool:
    return (
        snapshot.get("withdrawal_id") == withdrawal.id
        and snapshot.get("purchase_id") == purchase.id
        and snapshot.get("locale") == withdrawal.locale
    )


def valid_resolution_snapshot_decision(
    resolution: DbBillingWithdrawalResolution,
    *,
    snapshot: dict[str, Any],
    expected_adjustment_id: str | None,
) -> bool:
    return (
        snapshot.get("decision") == resolution.decision
        and snapshot.get("reason_code") == resolution.reason_code
        and snapshot.get("adjustment_id") == expected_adjustment_id
        and snapshot.get("mandatory_consumer_rights_preserved") is True
        and snapshot.get("resolved_at") == resolution.resolved_at
    )
