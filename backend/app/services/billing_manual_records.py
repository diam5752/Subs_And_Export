"""Immutable evidence for manual Stripe refunds and AADE adjustments."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.financial_records import (
    financial_retention_deadline,
)

ADJUSTMENT_RECORD_SCHEMA_VERSION = 1
WITHDRAWAL_RESOLUTION_SCHEMA_VERSION = 1
_PURCHASE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_INTERNAL_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACTOR_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STRIPE_REFUND_ID_RE = re.compile(r"^re_[A-Za-z0-9_]+$")
_AADE_DOCUMENT_TYPE_RE = re.compile(r"^[0-9]{1,2}(?:\.[0-9]{1,2})?$")
_AADE_AA_RE = re.compile(r"^[0-9]+$")
_AADE_MARK_RE = re.compile(r"^[1-9][0-9]{0,18}$")
_MAX_SIGNED_64_BIT_INTEGER = 9_223_372_036_854_775_807
_RESOLUTION_DECISIONS = {
    "accepted_refunded": "statutory_right_accepted",
    "rejected": "request_not_eligible",
}
WithdrawalResolutionDecision = Literal[
    "accepted_refunded",
    "rejected",
]


class BillingManualRecordError(RuntimeError):
    """Manual financial evidence is missing, malformed, or conflicting."""


def _canonical_json_bytes(
    value: dict[str, Any],
    *,
    pretty: bool = False,
) -> bytes:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=True,
    )
    return f"{rendered}\n".encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _deterministic_id(namespace: str, value: str) -> str:
    return hashlib.sha256(
        f"{namespace}:v1:{value}".encode(),
    ).hexdigest()[:32]


def _validate_actor_id(actor_user_id: str) -> None:
    if not _ACTOR_ID_RE.fullmatch(actor_user_id):
        raise BillingManualRecordError(
            "Billing actor identifier is invalid",
        )


def _validate_aade_identity(
    *,
    document_type: str,
    series: str,
    aa: str,
    mark: str,
) -> None:
    if (
        not _AADE_DOCUMENT_TYPE_RE.fullmatch(document_type)
        or not series
        or series.strip() != series
        or len(series) > 32
        or not _AADE_AA_RE.fullmatch(aa)
        or len(aa) > 64
        or not _AADE_MARK_RE.fullmatch(mark)
        or int(mark) > _MAX_SIGNED_64_BIT_INTEGER
    ):
        raise BillingManualRecordError(
            "AADE adjustment identity is invalid",
        )


def new_billing_adjustment_record(
    *,
    purchase: DbCreditPurchase,
    reversal: DbCreditPurchaseReversal,
    document_type: str,
    series: str,
    aa: str,
    mark: str,
    issued_at: int,
    actor_user_id: str,
    recorded_at: int,
) -> DbBillingAdjustmentRecord:
    """Build one append-only record for an already-completed manual refund."""
    _validate_actor_id(actor_user_id)
    _validate_aade_identity(
        document_type=document_type,
        series=series,
        aa=aa,
        mark=mark,
    )
    if (
        not _PURCHASE_ID_RE.fullmatch(str(purchase.id or ""))
        or not _INTERNAL_ID_RE.fullmatch(str(reversal.id or ""))
        or reversal.purchase_id != purchase.id
        or reversal.provider != "stripe"
        or reversal.kind != "refund"
        or not _STRIPE_REFUND_ID_RE.fullmatch(
            str(reversal.provider_reversal_id or ""),
        )
        or reversal.status != "succeeded"
        or reversal.active is not True
        or isinstance(reversal.amount_cents, bool)
        or reversal.amount_cents <= 0
        or not isinstance(reversal.currency, str)
        or reversal.currency.lower() != purchase.currency.lower()
        or reversal.currency != reversal.currency.lower()
    ):
        raise BillingManualRecordError(
            "A completed Stripe refund is required",
        )
    if (
        isinstance(issued_at, bool)
        or issued_at <= 0
        or issued_at < reversal.provider_event_created
        or isinstance(recorded_at, bool)
        or recorded_at < issued_at
    ):
        raise BillingManualRecordError(
            "AADE adjustment timestamps are invalid",
        )
    snapshot = {
        "schema_version": ADJUSTMENT_RECORD_SCHEMA_VERSION,
        "document_type": "gsubs_aade_refund_adjustment_record",
        "purchase_id": purchase.id,
        "reversal_id": reversal.id,
        "amount_cents": reversal.amount_cents,
        "currency": reversal.currency,
        "stripe": {
            "refund_id": reversal.provider_reversal_id,
            "status": reversal.status,
            "provider_event_created": reversal.provider_event_created,
        },
        "aade": {
            "provider": "aade_etimologio",
            "document_kind": "refund_adjustment",
            "document_type": document_type,
            "series": series,
            "aa": aa,
            "mark": mark,
            "issued_at": issued_at,
        },
        "recorded_at": recorded_at,
        "automatic_stripe_refund_executed": False,
        "automatic_aade_adjustment_executed": False,
    }
    retention_until = financial_retention_deadline(
        max(
            issued_at,
            recorded_at,
            reversal.provider_event_created,
            reversal.created_at,
            reversal.updated_at,
        ),
    )
    return DbBillingAdjustmentRecord(
        id=_deterministic_id(
            "gsubs-aade-refund-adjustment",
            reversal.id,
        ),
        purchase_id=purchase.id,
        reversal_id=reversal.id,
        schema_version=ADJUSTMENT_RECORD_SCHEMA_VERSION,
        provider="aade_etimologio",
        document_kind="refund_adjustment",
        aade_document_type=document_type,
        aade_series=series,
        aade_aa=aa,
        aade_mark=mark,
        issued_at=issued_at,
        amount_cents=reversal.amount_cents,
        currency=reversal.currency,
        recorded_by_user_id=actor_user_id,
        recorded_at=recorded_at,
        document_snapshot=snapshot,
        financial_retention_until=retention_until,
        created_at=recorded_at,
    )


def verify_billing_adjustment_record(
    record: DbBillingAdjustmentRecord,
    *,
    purchase: DbCreditPurchase | None = None,
    reversal: DbCreditPurchaseReversal | None = None,
) -> None:
    """Verify an adjustment without consulting mutable current policy text."""
    snapshot = record.document_snapshot
    if not isinstance(snapshot, dict):
        raise BillingManualRecordError(
            "AADE adjustment snapshot is invalid",
        )
    try:
        _validate_actor_id(record.recorded_by_user_id)
        _validate_aade_identity(
            document_type=record.aade_document_type,
            series=record.aade_series,
            aa=record.aade_aa,
            mark=record.aade_mark,
        )
    except (AttributeError, BillingManualRecordError) as exc:
        raise BillingManualRecordError(
            "AADE adjustment identity is invalid",
        ) from exc
    expected_snapshot = {
        "schema_version": ADJUSTMENT_RECORD_SCHEMA_VERSION,
        "document_type": "gsubs_aade_refund_adjustment_record",
        "purchase_id": record.purchase_id,
        "reversal_id": record.reversal_id,
        "amount_cents": record.amount_cents,
        "currency": record.currency,
        "stripe": {
            "refund_id": snapshot.get("stripe", {}).get("refund_id")
            if isinstance(snapshot.get("stripe"), dict)
            else None,
            "status": "succeeded",
            "provider_event_created": (
                snapshot.get("stripe", {}).get("provider_event_created")
                if isinstance(snapshot.get("stripe"), dict)
                else None
            ),
        },
        "aade": {
            "provider": record.provider,
            "document_kind": record.document_kind,
            "document_type": record.aade_document_type,
            "series": record.aade_series,
            "aa": record.aade_aa,
            "mark": record.aade_mark,
            "issued_at": record.issued_at,
        },
        "recorded_at": record.recorded_at,
        "automatic_stripe_refund_executed": False,
        "automatic_aade_adjustment_executed": False,
    }
    if (
        record.schema_version != ADJUSTMENT_RECORD_SCHEMA_VERSION
        or record.id
        != _deterministic_id(
            "gsubs-aade-refund-adjustment",
            record.reversal_id,
        )
        or not _PURCHASE_ID_RE.fullmatch(record.purchase_id)
        or not _INTERNAL_ID_RE.fullmatch(record.reversal_id)
        or record.provider != "aade_etimologio"
        or record.document_kind != "refund_adjustment"
        or isinstance(record.amount_cents, bool)
        or record.amount_cents <= 0
        or record.currency != record.currency.lower()
        or not re.fullmatch(r"[a-z]{3}", record.currency)
        or isinstance(record.issued_at, bool)
        or record.issued_at <= 0
        or isinstance(record.recorded_at, bool)
        or record.recorded_at < record.issued_at
        or record.created_at != record.recorded_at
        or record.financial_retention_until <= record.recorded_at
        or snapshot != expected_snapshot
    ):
        raise BillingManualRecordError(
            "AADE adjustment record conflicts with its identity",
        )
    stripe_snapshot = snapshot["stripe"]
    if (
        not isinstance(stripe_snapshot["refund_id"], str)
        or not _STRIPE_REFUND_ID_RE.fullmatch(
            stripe_snapshot["refund_id"],
        )
        or isinstance(
            stripe_snapshot["provider_event_created"],
            bool,
        )
        or not isinstance(
            stripe_snapshot["provider_event_created"],
            int,
        )
        or stripe_snapshot["provider_event_created"] <= 0
        or record.issued_at < stripe_snapshot["provider_event_created"]
    ):
        raise BillingManualRecordError(
            "AADE adjustment Stripe evidence is invalid",
        )
    if (purchase is None) != (reversal is None):
        raise BillingManualRecordError(
            "AADE adjustment parent evidence is incomplete",
        )
    if purchase is not None and reversal is not None:
        if (
            purchase.id != record.purchase_id
            or reversal.id != record.reversal_id
            or reversal.purchase_id != purchase.id
            or reversal.provider != "stripe"
            or reversal.kind != "refund"
            or reversal.provider_reversal_id != stripe_snapshot["refund_id"]
            or reversal.provider_event_created != stripe_snapshot["provider_event_created"]
            or reversal.amount_cents != record.amount_cents
            or reversal.currency != record.currency
        ):
            raise BillingManualRecordError(
                "AADE adjustment conflicts with Stripe evidence",
            )


def new_withdrawal_resolution(
    *,
    withdrawal: DbBillingWithdrawalRequest,
    purchase: DbCreditPurchase,
    decision: WithdrawalResolutionDecision,
    customer_explanation: str,
    actor_user_id: str,
    resolved_at: int,
    adjustment: DbBillingAdjustmentRecord | None = None,
    reversal: DbCreditPurchaseReversal | None = None,
) -> DbBillingWithdrawalResolution:
    """Build a terminal manual outcome; accepted means money and tax are done."""
    _validate_actor_id(actor_user_id)
    explanation = customer_explanation.strip()
    if explanation != customer_explanation or len(explanation) < 20 or len(explanation) > 1_000:
        raise BillingManualRecordError(
            "Customer resolution explanation is invalid",
        )
    reason_code = _RESOLUTION_DECISIONS.get(decision)
    if reason_code is None:
        raise BillingManualRecordError(
            "Withdrawal resolution decision is invalid",
        )
    if (
        withdrawal.purchase_id != purchase.id
        or withdrawal.locale not in {"el", "en"}
        or isinstance(resolved_at, bool)
        or resolved_at < withdrawal.submitted_at
    ):
        raise BillingManualRecordError(
            "Withdrawal resolution evidence is invalid",
        )
    adjustment_id: str | None = None
    manual_actions: dict[str, Any] | None = None
    retention_until = max(
        withdrawal.financial_retention_until,
        financial_retention_deadline(resolved_at),
    )
    if decision == "accepted_refunded":
        if adjustment is None or reversal is None:
            raise BillingManualRecordError(
                "Accepted withdrawal requires manual refund evidence",
            )
        verify_billing_adjustment_record(
            adjustment,
            purchase=purchase,
            reversal=reversal,
        )
        if reversal.status != "succeeded" or reversal.active is not True:
            raise BillingManualRecordError(
                "Accepted withdrawal requires a completed Stripe refund",
            )
        adjustment_id = adjustment.id
        manual_actions = {
            "performed_automatically": False,
            "stripe_refund_id": reversal.provider_reversal_id,
            "stripe_refund_status": reversal.status,
            "refunded_amount_cents": adjustment.amount_cents,
            "currency": adjustment.currency,
            "aade_adjustment_id": adjustment.id,
            "aade_document_type": adjustment.aade_document_type,
            "aade_series": adjustment.aade_series,
            "aade_aa": adjustment.aade_aa,
            "aade_mark": adjustment.aade_mark,
            "aade_issued_at": adjustment.issued_at,
        }
        retention_until = max(
            retention_until,
            adjustment.financial_retention_until,
        )
    elif adjustment is not None or reversal is not None:
        raise BillingManualRecordError(
            "Rejected withdrawal cannot claim manual refund evidence",
        )

    snapshot = {
        "schema_version": WITHDRAWAL_RESOLUTION_SCHEMA_VERSION,
        "document_type": "gsubs_withdrawal_resolution",
        "withdrawal_id": withdrawal.id,
        "purchase_id": purchase.id,
        "locale": withdrawal.locale,
        "decision": decision,
        "reason_code": reason_code,
        "adjustment_id": adjustment_id,
        "customer_explanation": explanation,
        "mandatory_consumer_rights_preserved": True,
        "manual_actions": manual_actions,
        "resolved_at": resolved_at,
    }
    resolution_bytes = _canonical_json_bytes(snapshot, pretty=True)
    return DbBillingWithdrawalResolution(
        id=_deterministic_id(
            "gsubs-withdrawal-resolution",
            withdrawal.id,
        ),
        withdrawal_id=withdrawal.id,
        purchase_id=purchase.id,
        adjustment_id=adjustment_id,
        schema_version=WITHDRAWAL_RESOLUTION_SCHEMA_VERSION,
        locale=withdrawal.locale,
        decision=decision,
        reason_code=reason_code,
        resolution_snapshot=snapshot,
        resolution_mime_type="application/json; charset=utf-8",
        resolution_filename=(f"gsubs-withdrawal-resolution-{purchase.id}.json"),
        resolution_bytes=resolution_bytes,
        resolution_sha256=_sha256(resolution_bytes),
        resolved_by_user_id=actor_user_id,
        resolved_at=resolved_at,
        available_at=resolved_at,
        financial_retention_until=retention_until,
        created_at=resolved_at,
    )


def verify_withdrawal_resolution(
    resolution: DbBillingWithdrawalResolution,
    *,
    withdrawal: DbBillingWithdrawalRequest,
    purchase: DbCreditPurchase,
    adjustment: DbBillingAdjustmentRecord | None = None,
    reversal: DbCreditPurchaseReversal | None = None,
) -> None:
    """Verify the immutable customer resolution and its external evidence."""
    snapshot = resolution.resolution_snapshot
    if not isinstance(snapshot, dict):
        raise BillingManualRecordError(
            "Withdrawal resolution snapshot is invalid",
        )
    try:
        _validate_actor_id(resolution.resolved_by_user_id)
    except (AttributeError, BillingManualRecordError) as exc:
        raise BillingManualRecordError(
            "Withdrawal resolution actor is invalid",
        ) from exc
    expected_reason = _RESOLUTION_DECISIONS.get(resolution.decision)
    expected_adjustment_id = adjustment.id if adjustment is not None else None
    explanation = snapshot.get("customer_explanation")
    if (
        resolution.schema_version != WITHDRAWAL_RESOLUTION_SCHEMA_VERSION
        or resolution.id
        != _deterministic_id(
            "gsubs-withdrawal-resolution",
            resolution.withdrawal_id,
        )
        or resolution.withdrawal_id != withdrawal.id
        or resolution.purchase_id != purchase.id
        or withdrawal.purchase_id != purchase.id
        or resolution.locale != withdrawal.locale
        or expected_reason is None
        or resolution.reason_code != expected_reason
        or resolution.adjustment_id != expected_adjustment_id
        or not isinstance(explanation, str)
        or explanation.strip() != explanation
        or len(explanation) < 20
        or len(explanation) > 1_000
        or resolution.resolution_mime_type != "application/json; charset=utf-8"
        or resolution.resolution_filename != f"gsubs-withdrawal-resolution-{purchase.id}.json"
        or not isinstance(resolution.resolution_bytes, bytes)
        or not _SHA256_RE.fullmatch(resolution.resolution_sha256)
        or _sha256(resolution.resolution_bytes) != resolution.resolution_sha256
        or isinstance(resolution.resolved_at, bool)
        or resolution.resolved_at < withdrawal.submitted_at
        or resolution.available_at != resolution.resolved_at
        or resolution.created_at != resolution.resolved_at
        or resolution.financial_retention_until <= resolution.resolved_at
    ):
        raise BillingManualRecordError(
            "Withdrawal resolution identity is invalid",
        )
    try:
        decoded = json.loads(resolution.resolution_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingManualRecordError(
            "Withdrawal resolution content is invalid",
        ) from exc
    if (
        decoded != snapshot
        or resolution.resolution_bytes != _canonical_json_bytes(snapshot, pretty=True)
        or set(snapshot)
        != {
            "schema_version",
            "document_type",
            "withdrawal_id",
            "purchase_id",
            "locale",
            "decision",
            "reason_code",
            "adjustment_id",
            "customer_explanation",
            "mandatory_consumer_rights_preserved",
            "manual_actions",
            "resolved_at",
        }
        or snapshot.get("schema_version") != WITHDRAWAL_RESOLUTION_SCHEMA_VERSION
        or snapshot.get("document_type") != "gsubs_withdrawal_resolution"
        or snapshot.get("withdrawal_id") != withdrawal.id
        or snapshot.get("purchase_id") != purchase.id
        or snapshot.get("locale") != withdrawal.locale
        or snapshot.get("decision") != resolution.decision
        or snapshot.get("reason_code") != resolution.reason_code
        or snapshot.get("adjustment_id") != expected_adjustment_id
        or snapshot.get("mandatory_consumer_rights_preserved") is not True
        or snapshot.get("resolved_at") != resolution.resolved_at
    ):
        raise BillingManualRecordError(
            "Withdrawal resolution conflicts with its identity",
        )
    if resolution.decision == "accepted_refunded":
        if adjustment is None or reversal is None:
            raise BillingManualRecordError(
                "Accepted withdrawal evidence is unavailable",
            )
        verify_billing_adjustment_record(
            adjustment,
            purchase=purchase,
            reversal=reversal,
        )
        expected_manual_actions = {
            "performed_automatically": False,
            "stripe_refund_id": reversal.provider_reversal_id,
            "stripe_refund_status": reversal.status,
            "refunded_amount_cents": adjustment.amount_cents,
            "currency": adjustment.currency,
            "aade_adjustment_id": adjustment.id,
            "aade_document_type": adjustment.aade_document_type,
            "aade_series": adjustment.aade_series,
            "aade_aa": adjustment.aade_aa,
            "aade_mark": adjustment.aade_mark,
            "aade_issued_at": adjustment.issued_at,
        }
        if (
            reversal.status != "succeeded"
            or reversal.active is not True
            or snapshot.get("manual_actions") != expected_manual_actions
        ):
            raise BillingManualRecordError(
                "Accepted withdrawal manual actions are invalid",
            )
    elif adjustment is not None or reversal is not None:
        raise BillingManualRecordError(
            "Rejected withdrawal evidence is invalid",
        )
    elif snapshot.get("manual_actions") is not None:
        raise BillingManualRecordError(
            "Rejected withdrawal cannot claim manual actions",
        )
