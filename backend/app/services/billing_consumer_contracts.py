"""Immutable consumer-contract confirmation primitives."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbCreditPurchase,
)
from backend.app.services.billing_manual_records import WithdrawalResolutionDecision
from backend.app.services.financial_records import financial_retention_deadline

WITHDRAWAL_SCHEMA_VERSION = 1
_CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1 = 1
_WITHDRAWAL_SCHEMA_VERSION_V1 = 1
_CONTRACT_CONFIRMATION_V1_SUPPORTED_DELIVERIES = frozenset(
    {
        (
            "account_vault",
            "available_pending_external_approval",
        ),
        (
            "account_vault",
            "available_approved",
        ),
    }
)
_WITHDRAWAL_V1_STATUS = "pending_manual_review"
_WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS = "pending_manual_review"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,63}$")
_PURCHASE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


class BillingConsumerRecordError(RuntimeError):
    """Base class for safe consumer-record failures."""


class BillingConsumerRecordNotFoundError(BillingConsumerRecordError):
    pass


class BillingConsumerRecordConflictError(BillingConsumerRecordError):
    pass


class BillingConsumerRecordValidationError(BillingConsumerRecordError):
    pass


@dataclass(frozen=True, slots=True)
class WithdrawalResult:
    withdrawal_id: str
    purchase_id: str
    status: str
    submitted_at: int
    timeliness_assessment_status: str
    acknowledgement_sha256: str


@dataclass(frozen=True, slots=True)
class BillingPurchaseSummary:
    purchase_id: str
    package_key: str
    credits: int
    amount_eur_cents: int
    currency: str
    status: str
    created_at: int
    fulfilled_at: int | None
    contract_confirmation_available: bool
    contract_concluded_at: int | None
    withdrawal_action_available: bool
    withdrawal_status: str | None
    withdrawal_acknowledgement_available: bool
    withdrawal_resolution_available: bool
    withdrawal_resolution_decision: WithdrawalResolutionDecision | None


def _canonical_json_bytes(value: dict[str, Any], *, pretty: bool = False) -> bytes:
    if pretty:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    else:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return f"{rendered}\n".encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _deterministic_id(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}:v1:{value}".encode()).hexdigest()[:32]


def _consumer_contract_snapshot_sha256_v1(
    snapshot: dict[str, Any],
) -> str:
    """Digest a v1 snapshot without depending on the current registry code."""
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _consumer_contract_snapshot(purchase: DbCreditPurchase) -> dict[str, Any]:
    purchase_snapshot = purchase.snapshot
    if not isinstance(purchase_snapshot, dict):
        raise BillingConsumerRecordValidationError(
            "Purchase snapshot is unavailable",
        )
    consumer_contract = purchase_snapshot.get("consumer_contract")
    if not isinstance(consumer_contract, dict):
        raise BillingConsumerRecordValidationError(
            "Consumer-contract snapshot is unavailable",
        )
    schema_version = consumer_contract.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != _CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1:
        raise BillingConsumerRecordValidationError(
            "Consumer-contract snapshot schema version is unsupported",
        )
    return _consumer_contract_snapshot_v1(
        purchase_snapshot=purchase_snapshot,
        consumer_contract=consumer_contract,
    )


def _consumer_contract_snapshot_v1(
    *,
    purchase_snapshot: dict[str, Any],
    consumer_contract: dict[str, Any],
) -> dict[str, Any]:
    """Read and validate the immutable v1 snapshot accepted at Checkout."""
    required_identity = (
        "schema_version",
        "disclosure_id",
        "disclosure_sha256",
        "locale",
        "policy_version",
        "terms_version",
        "withdrawal_notice_version",
        "confirmation_template_version",
        "contract_confirmation_delivery",
        "acceptances",
    )
    if any(not consumer_contract.get(field) for field in required_identity):
        raise BillingConsumerRecordValidationError(
            "Consumer-contract snapshot is incomplete",
        )
    try:
        expected_digest = _consumer_contract_snapshot_sha256_v1(
            consumer_contract,
        )
    except (TypeError, ValueError) as exc:
        raise BillingConsumerRecordValidationError(
            "Consumer-contract snapshot cannot be verified",
        ) from exc
    recorded_digest = purchase_snapshot.get("consumer_contract_sha256")
    if recorded_digest != expected_digest:
        raise BillingConsumerRecordValidationError(
            "Consumer-contract snapshot digest does not match",
        )
    _consumer_contract_accepted_at(consumer_contract)
    delivery = consumer_contract.get("contract_confirmation_delivery")
    launch_review_status = consumer_contract.get("launch_review_status")
    if (
        not isinstance(delivery, dict)
        or set(delivery) != {"channel", "status"}
        or (
            delivery.get("channel"),
            delivery.get("status"),
        )
        not in _CONTRACT_CONFIRMATION_V1_SUPPORTED_DELIVERIES
        or not isinstance(launch_review_status, dict)
        or launch_review_status.get("contract_confirmation_delivery") != delivery.get("status")
    ):
        raise BillingConsumerRecordValidationError(
            "Consumer-contract confirmation delivery is unsupported",
        )
    return consumer_contract


def _consumer_contract_accepted_at(
    consumer_contract: dict[str, Any],
) -> int:
    schema_version = consumer_contract.get("schema_version")
    if not isinstance(schema_version, bool) and schema_version == _CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1:
        return _consumer_contract_accepted_at_v1(consumer_contract)
    raise BillingConsumerRecordValidationError(
        "Consumer-contract acceptance schema version is unsupported",
    )


def _consumer_contract_accepted_at_v1(
    consumer_contract: dict[str, Any],
) -> int:
    accepted_at = consumer_contract.get("accepted_at")
    if isinstance(accepted_at, bool) or not isinstance(accepted_at, int) or accepted_at <= 0:
        raise BillingConsumerRecordValidationError(
            "Consumer-contract acceptance timestamp is invalid",
        )
    acceptance_texts = consumer_contract.get("required_acceptances")
    acceptances = consumer_contract.get("acceptances")
    if not isinstance(acceptance_texts, dict) or not isinstance(
        acceptances,
        dict,
    ):
        raise BillingConsumerRecordValidationError(
            "Consumer-contract acceptances are incomplete",
        )
    for key in (
        "terms",
        "immediate_performance",
        "withdrawal_consequences",
    ):
        accepted = acceptances.get(key)
        expected_text = acceptance_texts.get(key)
        if (
            not isinstance(accepted, dict)
            or accepted.get("accepted") is not True
            or accepted.get("accepted_at") != accepted_at
            or not isinstance(expected_text, str)
            or accepted.get("text") != expected_text
            or accepted.get("text_sha256") != hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
        ):
            raise BillingConsumerRecordValidationError(
                "Consumer-contract acceptances are incomplete",
            )
    return accepted_at


def _contract_confirmation_content(
    *,
    purchase: DbCreditPurchase,
    consumer_contract: dict[str, Any],
    consumer_contract_sha256: str,
    contract_concluded_at: int,
    available_at: int,
    schema_version: int,
    delivery_channel: str,
    delivery_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "document_type": "gsubs_consumer_contract_confirmation",
        "delivery_channel": delivery_channel,
        "delivery_status": delivery_status,
        "contract_concluded_at": contract_concluded_at,
        "available_at": available_at,
        "purchase": {
            "purchase_id": purchase.id,
            "package_key": purchase.package_key,
            "credits": purchase.credits,
            "gross_amount_cents": purchase.amount_eur_cents,
            "currency": purchase.currency.lower(),
            "checkout_session_id": purchase.checkout_session_id,
            "payment_intent_id": purchase.payment_intent_id,
        },
        "consumer_contract_sha256": consumer_contract_sha256,
        "consumer_contract": consumer_contract,
        "tax_document_notice": {
            "stripe_receipt_is_aade_tax_document": False,
            "aade_document_status": "pending_manual_issue",
        },
    }


def new_contract_confirmation(
    *,
    purchase: DbCreditPurchase,
    contract_concluded_at: int,
    generated_at: int,
) -> DbBillingContractConfirmation:
    """Create the exact durable artifact that must precede credit fulfillment."""
    if isinstance(contract_concluded_at, bool) or contract_concluded_at <= 0:
        raise BillingConsumerRecordValidationError(
            "Contract conclusion timestamp is invalid",
        )
    if isinstance(generated_at, bool) or generated_at <= 0 or generated_at < contract_concluded_at:
        raise BillingConsumerRecordValidationError(
            "Contract confirmation generation timestamp is invalid",
        )
    consumer_contract = _consumer_contract_snapshot(purchase)
    if _consumer_contract_accepted_at(consumer_contract) > contract_concluded_at:
        raise BillingConsumerRecordValidationError(
            "Contract conclusion precedes consumer acceptance",
        )
    locale = str(consumer_contract["locale"])
    if locale not in {"el", "en"}:
        raise BillingConsumerRecordValidationError(
            "Consumer-contract locale is invalid",
        )
    purchase_snapshot = purchase.snapshot
    consumer_digest = str(purchase_snapshot["consumer_contract_sha256"])
    schema_version = consumer_contract["schema_version"]
    delivery = consumer_contract["contract_confirmation_delivery"]
    if (
        isinstance(schema_version, bool)
        or schema_version != _CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1
        or not isinstance(delivery, dict)
    ):
        raise BillingConsumerRecordValidationError(
            "Consumer-contract confirmation format is unsupported",
        )
    delivery_channel = str(delivery.get("channel") or "")
    delivery_status = str(delivery.get("status") or "")
    content = _contract_confirmation_content(
        purchase=purchase,
        consumer_contract=consumer_contract,
        consumer_contract_sha256=consumer_digest,
        contract_concluded_at=contract_concluded_at,
        available_at=generated_at,
        schema_version=schema_version,
        delivery_channel=delivery_channel,
        delivery_status=delivery_status,
    )
    content_bytes = _canonical_json_bytes(content, pretty=True)
    content_sha256 = _sha256(content_bytes)
    return DbBillingContractConfirmation(
        id=_deterministic_id("gsubs-contract-confirmation", purchase.id),
        purchase_id=purchase.id,
        schema_version=schema_version,
        locale=locale,
        contract_concluded_at=contract_concluded_at,
        mime_type="application/json; charset=utf-8",
        filename=f"gsubs-contract-{purchase.id}.json",
        content_bytes=content_bytes,
        content_sha256=content_sha256,
        consumer_contract_sha256=consumer_digest,
        delivery_channel=delivery_channel,
        delivery_status=delivery_status,
        available_at=generated_at,
        financial_retention_until=financial_retention_deadline(
            max(contract_concluded_at, generated_at),
        ),
        created_at=generated_at,
    )


def verify_contract_confirmation(
    confirmation: DbBillingContractConfirmation,
    *,
    purchase: DbCreditPurchase | None = None,
) -> None:
    """Dispatch immutable contract evidence to its version-owned reader."""
    if (
        type(confirmation.schema_version) is int
        and confirmation.schema_version == _CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1
    ):
        _verify_contract_confirmation_v1(
            confirmation,
            purchase=purchase,
        )
        return
    raise BillingConsumerRecordConflictError(
        "Contract confirmation schema version is unsupported",
    )


def _verify_contract_confirmation_v1(
    confirmation: DbBillingContractConfirmation,
    *,
    purchase: DbCreditPurchase | None = None,
) -> None:
    """Verify v1 evidence without consulting the mutable current registry."""
    _verify_contract_confirmation_digest_v1(confirmation)
    _verify_contract_confirmation_identity_v1(confirmation)
    decoded, decoded_purchase, decoded_consumer_contract = _decode_contract_confirmation_v1(
        confirmation,
    )
    _verify_contract_confirmation_content_identity_v1(
        confirmation,
        decoded=decoded,
        decoded_purchase=decoded_purchase,
        decoded_consumer_contract=decoded_consumer_contract,
    )
    if purchase is not None:
        _verify_contract_confirmation_purchase_v1(
            confirmation,
            decoded=decoded,
            purchase=purchase,
        )


def _verify_contract_confirmation_digest_v1(
    confirmation: DbBillingContractConfirmation,
) -> None:
    if (
        not isinstance(confirmation.content_bytes, bytes)
        or _sha256(confirmation.content_bytes) != confirmation.content_sha256
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation digest does not match",
        )


def _verify_contract_confirmation_identity_v1(
    confirmation: DbBillingContractConfirmation,
) -> None:
    if not _contract_confirmation_storage_identity_is_valid_v1(confirmation):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation identity is invalid",
        )
    if not _contract_confirmation_timing_is_valid_v1(confirmation):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation identity is invalid",
        )
    if not _contract_confirmation_digests_are_valid_v1(confirmation):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation identity is invalid",
        )


def _contract_confirmation_storage_identity_is_valid_v1(
    confirmation: DbBillingContractConfirmation,
) -> bool:
    expected_id = _deterministic_id(
        "gsubs-contract-confirmation",
        confirmation.purchase_id,
    )
    expected_filename = f"gsubs-contract-{confirmation.purchase_id}.json"
    return (
        type(confirmation.schema_version) is int
        and confirmation.schema_version == _CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1
        and isinstance(confirmation.purchase_id, str)
        and _PURCHASE_ID_RE.fullmatch(confirmation.purchase_id) is not None
        and confirmation.id == expected_id
        and confirmation.locale in {"el", "en"}
        and confirmation.mime_type == "application/json; charset=utf-8"
        and confirmation.filename == expected_filename
        and (
            confirmation.delivery_channel,
            confirmation.delivery_status,
        )
        in _CONTRACT_CONFIRMATION_V1_SUPPORTED_DELIVERIES
    )


def _contract_confirmation_timing_is_valid_v1(
    confirmation: DbBillingContractConfirmation,
) -> bool:
    if (
        type(confirmation.contract_concluded_at) is not int
        or type(confirmation.available_at) is not int
        or type(confirmation.created_at) is not int
        or type(confirmation.financial_retention_until) is not int
    ):
        return False
    retention_origin = max(
        confirmation.contract_concluded_at,
        confirmation.available_at,
    )
    return (
        confirmation.contract_concluded_at > 0
        and confirmation.available_at > 0
        and confirmation.available_at >= confirmation.contract_concluded_at
        and confirmation.created_at == confirmation.available_at
        and confirmation.financial_retention_until > retention_origin
    )


def _contract_confirmation_digests_are_valid_v1(
    confirmation: DbBillingContractConfirmation,
) -> bool:
    return (
        isinstance(confirmation.content_sha256, str)
        and _SHA256_RE.fullmatch(confirmation.content_sha256) is not None
        and isinstance(confirmation.consumer_contract_sha256, str)
        and _SHA256_RE.fullmatch(confirmation.consumer_contract_sha256) is not None
    )


def _decode_contract_confirmation_v1(
    confirmation: DbBillingContractConfirmation,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        decoded = json.loads(confirmation.content_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content is invalid",
        ) from exc
    if not isinstance(decoded, dict):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content is invalid",
        )
    if confirmation.content_bytes != _canonical_json_bytes(
        decoded,
        pretty=True,
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content is not canonical",
        )
    decoded_purchase = decoded.get("purchase")
    decoded_consumer_contract = decoded.get("consumer_contract")
    if not isinstance(decoded_purchase, dict) or not isinstance(decoded_consumer_contract, dict):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content is invalid",
        )
    return decoded, decoded_purchase, decoded_consumer_contract


def _verify_contract_confirmation_content_identity_v1(
    confirmation: DbBillingContractConfirmation,
    *,
    decoded: dict[str, Any],
    decoded_purchase: dict[str, Any],
    decoded_consumer_contract: dict[str, Any],
) -> None:
    decoded_contract_digest, accepted_at = _decoded_consumer_evidence_v1(
        decoded_consumer_contract,
    )
    if not _decoded_contract_header_matches_v1(
        confirmation,
        decoded=decoded,
        decoded_purchase=decoded_purchase,
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content conflicts with its identity",
        )
    if not _decoded_consumer_evidence_matches_v1(
        confirmation,
        decoded=decoded,
        decoded_consumer_contract=decoded_consumer_contract,
        decoded_contract_digest=decoded_contract_digest,
        accepted_at=accepted_at,
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content conflicts with its identity",
        )


def _decoded_consumer_evidence_v1(
    decoded_consumer_contract: dict[str, Any],
) -> tuple[str, int]:
    try:
        return (
            _consumer_contract_snapshot_sha256_v1(decoded_consumer_contract),
            _consumer_contract_accepted_at(decoded_consumer_contract),
        )
    except (
        BillingConsumerRecordValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise BillingConsumerRecordConflictError(
            "Contract confirmation consumer evidence is invalid",
        ) from exc


def _decoded_contract_header_matches_v1(
    confirmation: DbBillingContractConfirmation,
    *,
    decoded: dict[str, Any],
    decoded_purchase: dict[str, Any],
) -> bool:
    return (
        set(decoded)
        == {
            "schema_version",
            "document_type",
            "delivery_channel",
            "delivery_status",
            "contract_concluded_at",
            "available_at",
            "purchase",
            "consumer_contract_sha256",
            "consumer_contract",
            "tax_document_notice",
        }
        and decoded.get("schema_version") == confirmation.schema_version
        and decoded.get("document_type") == "gsubs_consumer_contract_confirmation"
        and decoded.get("delivery_channel") == confirmation.delivery_channel
        and decoded.get("delivery_status") == confirmation.delivery_status
        and decoded.get("contract_concluded_at") == confirmation.contract_concluded_at
        and decoded.get("available_at") == confirmation.available_at
        and decoded_purchase.get("purchase_id") == confirmation.purchase_id
        and set(decoded_purchase)
        == {
            "purchase_id",
            "package_key",
            "credits",
            "gross_amount_cents",
            "currency",
            "checkout_session_id",
            "payment_intent_id",
        }
    )


def _decoded_consumer_evidence_matches_v1(
    confirmation: DbBillingContractConfirmation,
    *,
    decoded: dict[str, Any],
    decoded_consumer_contract: dict[str, Any],
    decoded_contract_digest: str,
    accepted_at: int,
) -> bool:
    return (
        decoded.get("consumer_contract_sha256") == confirmation.consumer_contract_sha256
        and decoded_contract_digest == confirmation.consumer_contract_sha256
        and decoded_consumer_contract.get("locale") == confirmation.locale
        and accepted_at <= confirmation.contract_concluded_at
        and decoded.get("tax_document_notice")
        == {
            "stripe_receipt_is_aade_tax_document": False,
            "aade_document_status": "pending_manual_issue",
        }
    )


def _verify_contract_confirmation_purchase_v1(
    confirmation: DbBillingContractConfirmation,
    *,
    decoded: dict[str, Any],
    purchase: DbCreditPurchase,
) -> None:
    try:
        consumer_contract = _consumer_contract_snapshot(purchase)
    except BillingConsumerRecordValidationError as exc:
        raise BillingConsumerRecordConflictError(
            "Contract confirmation conflicts with purchase evidence",
        ) from exc
    expected_digest = purchase.snapshot.get(
        "consumer_contract_sha256",
    )
    expected_delivery = consumer_contract.get(
        "contract_confirmation_delivery",
    )
    if not isinstance(expected_delivery, dict):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation conflicts with purchase evidence",
        )
    expected_content = _contract_confirmation_content(
        purchase=purchase,
        consumer_contract=consumer_contract,
        consumer_contract_sha256=str(expected_digest),
        contract_concluded_at=confirmation.contract_concluded_at,
        available_at=confirmation.available_at,
        schema_version=confirmation.schema_version,
        delivery_channel=confirmation.delivery_channel,
        delivery_status=confirmation.delivery_status,
    )
    if (
        confirmation.purchase_id != purchase.id
        or confirmation.locale != consumer_contract.get("locale")
        or confirmation.consumer_contract_sha256 != expected_digest
        or confirmation.delivery_channel != expected_delivery.get("channel")
        or confirmation.delivery_status != expected_delivery.get("status")
        or decoded != expected_content
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation conflicts with purchase evidence",
        )
