"""Pure identity checks for immutable consumer-withdrawal evidence."""

from __future__ import annotations

from typing import Any, cast

from backend.app.db.models import DbBillingWithdrawalRequest
from backend.app.services.billing_consumer_contracts import (
    _EMAIL_RE,
    _PURCHASE_ID_RE,
    _SHA256_RE,
    _WITHDRAWAL_SCHEMA_VERSION_V1,
    _WITHDRAWAL_V1_STATUS,
    _WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS,
    BillingConsumerRecordConflictError,
    _deterministic_id,
)

_WITHDRAWAL_REQUEST_KEYS = {
    "schema_version",
    "request_type",
    "purchase_id",
    "locale",
    "statement",
    "confirmed_name",
    "confirmation_electronic_means",
    "submitted_at",
    "contract_concluded_at",
    "timeliness_assessment_status",
    "status",
    "automatic_stripe_refund_executed",
    "automatic_aade_adjustment_executed",
}


def validate_withdrawal_identity(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    normalized_idempotency_key: str,
) -> None:
    if not (
        _valid_record_identity(withdrawal, normalized_idempotency_key)
        and _valid_record_timestamps(withdrawal)
        and _valid_record_digests(withdrawal)
    ):
        raise BillingConsumerRecordConflictError("Withdrawal acknowledgement identity is invalid")


def _valid_record_identity(
    withdrawal: DbBillingWithdrawalRequest,
    normalized_idempotency_key: str,
) -> bool:
    return (
        type(withdrawal.schema_version) is int
        and withdrawal.schema_version == _WITHDRAWAL_SCHEMA_VERSION_V1
        and isinstance(withdrawal.purchase_id, str)
        and _PURCHASE_ID_RE.fullmatch(withdrawal.purchase_id) is not None
        and withdrawal.locale in {"el", "en"}
        and withdrawal.status == _WITHDRAWAL_V1_STATUS
        and normalized_idempotency_key == withdrawal.idempotency_key
        and withdrawal.acknowledgement_mime_type == "application/json; charset=utf-8"
        and withdrawal.acknowledgement_filename == f"gsubs-withdrawal-{withdrawal.purchase_id}.json"
    )


def _valid_record_timestamps(withdrawal: DbBillingWithdrawalRequest) -> bool:
    return (
        type(withdrawal.submitted_at) is int
        and withdrawal.submitted_at > 0
        and type(withdrawal.available_at) is int
        and type(withdrawal.created_at) is int
        and type(withdrawal.financial_retention_until) is int
        and withdrawal.available_at == withdrawal.submitted_at
        and withdrawal.created_at == withdrawal.submitted_at
        and withdrawal.financial_retention_until > withdrawal.submitted_at
        and withdrawal.id
        == _deterministic_id("gsubs-withdrawal", f"{withdrawal.purchase_id}:{withdrawal.submitted_at}")
    )


def _valid_record_digests(withdrawal: DbBillingWithdrawalRequest) -> bool:
    return (
        isinstance(withdrawal.request_sha256, str)
        and _SHA256_RE.fullmatch(withdrawal.request_sha256) is not None
        and isinstance(withdrawal.acknowledgement_sha256, str)
        and _SHA256_RE.fullmatch(withdrawal.acknowledgement_sha256) is not None
    )


def validated_withdrawal_concluded_at(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    request_snapshot: dict[str, Any],
    expected_statement: str,
) -> int:
    concluded_at = request_snapshot.get("contract_concluded_at")
    if not (
        _valid_snapshot_identity(withdrawal, request_snapshot, expected_statement)
        and _valid_snapshot_contact(request_snapshot)
        and _valid_snapshot_timing(withdrawal, request_snapshot, concluded_at)
        and _valid_snapshot_status(withdrawal, request_snapshot)
    ):
        raise BillingConsumerRecordConflictError("Withdrawal request conflicts with its identity")
    return cast(int, concluded_at)


def _valid_snapshot_identity(
    withdrawal: DbBillingWithdrawalRequest,
    snapshot: dict[str, Any],
    expected_statement: str,
) -> bool:
    return (
        set(snapshot) == _WITHDRAWAL_REQUEST_KEYS
        and snapshot.get("schema_version") == withdrawal.schema_version
        and snapshot.get("request_type") == "consumer_contract_withdrawal"
        and snapshot.get("purchase_id") == withdrawal.purchase_id
        and snapshot.get("locale") == withdrawal.locale
        and snapshot.get("statement") == expected_statement
    )


def _valid_snapshot_contact(snapshot: dict[str, Any]) -> bool:
    return _valid_confirmed_name(snapshot.get("confirmed_name")) and _valid_electronic_means(
        snapshot.get("confirmation_electronic_means")
    )


def _valid_confirmed_name(value: object) -> bool:
    return isinstance(value, str) and value.strip() == value and bool(value) and len(value) <= 100


def _valid_electronic_means(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"type", "address", "delivery_status"}:
        return False
    address = value.get("address")
    return (
        value.get("type") == "email"
        and value.get("delivery_status") == "not_sent_transactional_channel_not_ready"
        and isinstance(address, str)
        and address.strip() == address
        and len(address) <= 255
        and _EMAIL_RE.fullmatch(address) is not None
    )


def _valid_snapshot_timing(
    withdrawal: DbBillingWithdrawalRequest,
    snapshot: dict[str, Any],
    concluded_at: object,
) -> bool:
    return (
        snapshot.get("submitted_at") == withdrawal.submitted_at
        and not isinstance(concluded_at, bool)
        and isinstance(concluded_at, int)
        and concluded_at > 0
        and withdrawal.submitted_at >= concluded_at
    )


def _valid_snapshot_status(
    withdrawal: DbBillingWithdrawalRequest,
    snapshot: dict[str, Any],
) -> bool:
    return (
        snapshot.get("timeliness_assessment_status") == _WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS
        and snapshot.get("status") == withdrawal.status
        and snapshot.get("automatic_stripe_refund_executed") is False
        and snapshot.get("automatic_aade_adjustment_executed") is False
    )
