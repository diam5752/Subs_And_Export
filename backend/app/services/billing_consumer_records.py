"""Immutable consumer-contract confirmations and withdrawal acknowledgements."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select, text

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbBillingWithdrawalRequest,
    DbCreditPurchase,
)
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
    if (
        not isinstance(confirmation.content_bytes, bytes)
        or _sha256(confirmation.content_bytes) != confirmation.content_sha256
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation digest does not match",
        )
    if (
        type(confirmation.schema_version) is not int
        or confirmation.schema_version != _CONTRACT_CONFIRMATION_SCHEMA_VERSION_V1
        or not isinstance(confirmation.purchase_id, str)
        or not _PURCHASE_ID_RE.fullmatch(confirmation.purchase_id)
        or confirmation.id
        != _deterministic_id(
            "gsubs-contract-confirmation",
            confirmation.purchase_id,
        )
        or confirmation.locale not in {"el", "en"}
        or confirmation.mime_type != "application/json; charset=utf-8"
        or confirmation.filename != f"gsubs-contract-{confirmation.purchase_id}.json"
        or (
            confirmation.delivery_channel,
            confirmation.delivery_status,
        )
        not in _CONTRACT_CONFIRMATION_V1_SUPPORTED_DELIVERIES
        or type(confirmation.contract_concluded_at) is not int
        or confirmation.contract_concluded_at <= 0
        or type(confirmation.available_at) is not int
        or confirmation.available_at <= 0
        or type(confirmation.created_at) is not int
        or type(confirmation.financial_retention_until) is not int
        or confirmation.available_at < confirmation.contract_concluded_at
        or confirmation.created_at != confirmation.available_at
        or confirmation.financial_retention_until
        <= max(
            confirmation.contract_concluded_at,
            confirmation.available_at,
        )
        or not isinstance(confirmation.content_sha256, str)
        or not _SHA256_RE.fullmatch(confirmation.content_sha256)
        or not isinstance(
            confirmation.consumer_contract_sha256,
            str,
        )
        or not _SHA256_RE.fullmatch(
            confirmation.consumer_contract_sha256,
        )
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation identity is invalid",
        )
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
    try:
        decoded_contract_digest = _consumer_contract_snapshot_sha256_v1(
            decoded_consumer_contract,
        )
        accepted_at = _consumer_contract_accepted_at(
            decoded_consumer_contract,
        )
    except (
        BillingConsumerRecordValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise BillingConsumerRecordConflictError(
            "Contract confirmation consumer evidence is invalid",
        ) from exc
    if (
        set(decoded)
        != {
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
        or decoded.get("schema_version") != confirmation.schema_version
        or decoded.get("document_type") != "gsubs_consumer_contract_confirmation"
        or decoded.get("delivery_channel") != confirmation.delivery_channel
        or decoded.get("delivery_status") != confirmation.delivery_status
        or decoded.get("contract_concluded_at") != confirmation.contract_concluded_at
        or decoded.get("available_at") != confirmation.available_at
        or decoded_purchase.get("purchase_id") != confirmation.purchase_id
        or set(decoded_purchase)
        != {
            "purchase_id",
            "package_key",
            "credits",
            "gross_amount_cents",
            "currency",
            "checkout_session_id",
            "payment_intent_id",
        }
        or decoded.get("consumer_contract_sha256") != confirmation.consumer_contract_sha256
        or decoded_contract_digest != confirmation.consumer_contract_sha256
        or decoded_consumer_contract.get("locale") != confirmation.locale
        or accepted_at > confirmation.contract_concluded_at
        or decoded.get("tax_document_notice")
        != {
            "stripe_receipt_is_aade_tax_document": False,
            "aade_document_status": "pending_manual_issue",
        }
    ):
        raise BillingConsumerRecordConflictError(
            "Contract confirmation content conflicts with its identity",
        )
    if purchase is None:
        return
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


class BillingConsumerRecordStore:
    """Authenticated access and idempotent receipt of withdrawal requests."""

    def __init__(self, *, db: Database) -> None:
        self.db = db

    def get_contract_confirmation(
        self,
        *,
        user_id: str,
        purchase_id: str,
    ) -> DbBillingContractConfirmation:
        with self.db.session() as session:
            owned_record = session.execute(
                select(
                    DbBillingContractConfirmation,
                    DbCreditPurchase,
                )
                .join(
                    DbCreditPurchase,
                    DbCreditPurchase.id == DbBillingContractConfirmation.purchase_id,
                )
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase_id,
                    DbCreditPurchase.user_id == user_id,
                )
                .limit(1)
            ).one_or_none()
        if owned_record is None:
            raise BillingConsumerRecordNotFoundError(
                "Contract confirmation not found",
            )
        confirmation, purchase = owned_record
        verify_contract_confirmation(
            confirmation,
            purchase=purchase,
        )
        return cast(DbBillingContractConfirmation, confirmation)

    def list_purchases(
        self,
        *,
        user_id: str,
    ) -> tuple[BillingPurchaseSummary, ...]:
        with self.db.session() as session:
            purchases = tuple(
                session.scalars(
                    select(DbCreditPurchase)
                    .where(DbCreditPurchase.user_id == user_id)
                    .order_by(
                        DbCreditPurchase.created_at.desc(),
                        DbCreditPurchase.id.desc(),
                    )
                )
            )
            purchase_ids = [purchase.id for purchase in purchases]
            if not purchase_ids:
                return ()
            confirmations = {
                confirmation.purchase_id: confirmation
                for confirmation in session.scalars(
                    select(DbBillingContractConfirmation).where(
                        DbBillingContractConfirmation.purchase_id.in_(
                            purchase_ids,
                        )
                    )
                )
            }
            withdrawals = {
                withdrawal.purchase_id: withdrawal
                for withdrawal in session.scalars(
                    select(DbBillingWithdrawalRequest).where(
                        DbBillingWithdrawalRequest.purchase_id.in_(
                            purchase_ids,
                        )
                    )
                )
            }

        summaries: list[BillingPurchaseSummary] = []
        for purchase in purchases:
            confirmation = confirmations.get(purchase.id)
            withdrawal = withdrawals.get(purchase.id)
            if confirmation is not None:
                verify_contract_confirmation(
                    confirmation,
                    purchase=purchase,
                )
            if withdrawal is not None:
                self._verify_withdrawal(
                    withdrawal,
                    purchase=purchase,
                    confirmation=confirmation,
                )
            concluded_at = confirmation.contract_concluded_at if confirmation is not None else None
            summaries.append(
                BillingPurchaseSummary(
                    purchase_id=purchase.id,
                    package_key=purchase.package_key,
                    credits=purchase.credits,
                    amount_eur_cents=purchase.amount_eur_cents,
                    currency=purchase.currency.lower(),
                    status=purchase.status,
                    created_at=purchase.created_at,
                    fulfilled_at=purchase.fulfilled_at,
                    contract_confirmation_available=confirmation is not None,
                    contract_concluded_at=concluded_at,
                    withdrawal_action_available=(confirmation is not None and withdrawal is None),
                    withdrawal_status=(withdrawal.status if withdrawal is not None else None),
                    withdrawal_acknowledgement_available=(withdrawal is not None),
                )
            )
        return tuple(summaries)

    def submit_withdrawal(
        self,
        *,
        user_id: str,
        purchase_id: str,
        idempotency_key: str,
        locale: str,
        withdrawal_requested: bool,
        confirmed_name: str,
        confirmation_email: str,
        submitted_at: int | None = None,
    ) -> WithdrawalResult:
        normalized_key = self._validate_idempotency_key(idempotency_key)
        if locale not in {"el", "en"}:
            raise BillingConsumerRecordValidationError(
                "Unsupported withdrawal locale",
            )
        if type(withdrawal_requested) is not bool or withdrawal_requested is not True:
            raise BillingConsumerRecordValidationError(
                "An express withdrawal request is required",
            )
        normalized_name = confirmed_name.strip()
        normalized_email = confirmation_email.strip()
        if normalized_name != confirmed_name or not normalized_name or len(normalized_name) > 100:
            raise BillingConsumerRecordValidationError(
                "Confirmed customer name is invalid",
            )
        if (
            normalized_email != confirmation_email
            or len(normalized_email) > 255
            or not _EMAIL_RE.fullmatch(normalized_email)
        ):
            raise BillingConsumerRecordValidationError(
                "Confirmation email is invalid",
            )
        received_at = int(time.time()) if submitted_at is None else submitted_at
        if isinstance(received_at, bool) or received_at <= 0:
            raise BillingConsumerRecordValidationError(
                "Withdrawal timestamp is invalid",
            )
        with self.db.session() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {
                    "lock_key": self._advisory_lock_key(
                        f"billing-withdrawal:{normalized_key}",
                    )
                },
            )
            existing_by_key = session.scalar(
                select(DbBillingWithdrawalRequest)
                .where(
                    DbBillingWithdrawalRequest.idempotency_key == normalized_key,
                )
                .limit(1)
            )
            if existing_by_key is not None:
                purchase = session.get(
                    DbCreditPurchase,
                    existing_by_key.purchase_id,
                )
                if (
                    purchase is None
                    or purchase.user_id != user_id
                    or existing_by_key.purchase_id != purchase_id
                ):
                    raise BillingConsumerRecordConflictError(
                        "Idempotency key was used for another withdrawal request",
                    )
                confirmation = session.scalar(
                    select(DbBillingContractConfirmation)
                    .where(
                        DbBillingContractConfirmation.purchase_id == purchase.id,
                    )
                    .limit(1)
                )
                if confirmation is None:
                    raise BillingConsumerRecordConflictError(
                        "The purchase has no concluded contract confirmation",
                    )
                self._assert_withdrawal_replay_equivalent(
                    existing_by_key,
                    purchase=purchase,
                    confirmation=confirmation,
                    locale=locale,
                    normalized_name=normalized_name,
                    normalized_email=normalized_email,
                    conflict_message=(
                        "Idempotency key was used for another withdrawal request"
                    ),
                )
                return self._withdrawal_result(
                    existing_by_key,
                    purchase=purchase,
                    confirmation=confirmation,
                )

            purchase = session.scalar(
                select(DbCreditPurchase)
                .where(
                    DbCreditPurchase.id == purchase_id,
                    DbCreditPurchase.user_id == user_id,
                )
                .with_for_update()
                .limit(1)
            )
            if purchase is None:
                raise BillingConsumerRecordNotFoundError(
                    "Purchase not found",
                )
            confirmation = session.scalar(
                select(DbBillingContractConfirmation)
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase.id,
                )
                .limit(1)
            )
            if confirmation is None:
                raise BillingConsumerRecordConflictError(
                    "The purchase has no concluded contract confirmation",
                )
            verify_contract_confirmation(confirmation, purchase=purchase)

            existing_for_purchase = session.scalar(
                select(DbBillingWithdrawalRequest)
                .where(
                    DbBillingWithdrawalRequest.purchase_id == purchase.id,
                )
                .limit(1)
            )
            if existing_for_purchase is not None:
                self._assert_withdrawal_replay_equivalent(
                    existing_for_purchase,
                    purchase=purchase,
                    confirmation=confirmation,
                    locale=locale,
                    normalized_name=normalized_name,
                    normalized_email=normalized_email,
                    conflict_message=(
                        "A withdrawal request already exists for this purchase "
                        "with different details"
                    ),
                )
                return self._withdrawal_result(
                    existing_for_purchase,
                    purchase=purchase,
                    confirmation=confirmation,
                )

            if WITHDRAWAL_SCHEMA_VERSION != _WITHDRAWAL_SCHEMA_VERSION_V1:
                raise BillingConsumerRecordValidationError(
                    "Withdrawal acknowledgement schema version is unsupported",
                )
            statement = self._withdrawal_statement(
                locale,
                purchase_id=purchase.id,
            )
            request_snapshot = {
                "schema_version": _WITHDRAWAL_SCHEMA_VERSION_V1,
                "request_type": "consumer_contract_withdrawal",
                "purchase_id": purchase.id,
                "locale": locale,
                "statement": statement,
                "confirmed_name": normalized_name,
                "confirmation_electronic_means": {
                    "type": "email",
                    "address": normalized_email,
                    "delivery_status": ("not_sent_transactional_channel_not_ready"),
                },
                "submitted_at": received_at,
                "contract_concluded_at": confirmation.contract_concluded_at,
                "timeliness_assessment_status": (_WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS),
                "status": _WITHDRAWAL_V1_STATUS,
                "automatic_stripe_refund_executed": False,
                "automatic_aade_adjustment_executed": False,
            }
            request_bytes = _canonical_json_bytes(request_snapshot)
            request_sha256 = _sha256(request_bytes)
            acknowledgement = {
                **request_snapshot,
                "document_type": "gsubs_withdrawal_acknowledgement",
                "request_sha256": request_sha256,
                "receipt_notice": self._receipt_notice(locale),
            }
            acknowledgement_bytes = _canonical_json_bytes(
                acknowledgement,
                pretty=True,
            )
            withdrawal = DbBillingWithdrawalRequest(
                id=_deterministic_id(
                    "gsubs-withdrawal",
                    f"{purchase.id}:{received_at}",
                ),
                purchase_id=purchase.id,
                idempotency_key=normalized_key,
                schema_version=_WITHDRAWAL_SCHEMA_VERSION_V1,
                locale=locale,
                status=_WITHDRAWAL_V1_STATUS,
                request_snapshot=request_snapshot,
                request_bytes=request_bytes,
                request_sha256=request_sha256,
                submitted_at=received_at,
                acknowledgement_mime_type="application/json; charset=utf-8",
                acknowledgement_filename=(f"gsubs-withdrawal-{purchase.id}.json"),
                acknowledgement_bytes=acknowledgement_bytes,
                acknowledgement_sha256=_sha256(acknowledgement_bytes),
                available_at=received_at,
                financial_retention_until=max(
                    confirmation.financial_retention_until,
                    financial_retention_deadline(received_at),
                ),
                created_at=received_at,
            )
            session.add(withdrawal)
            session.flush()
            return self._withdrawal_result(
                withdrawal,
                purchase=purchase,
                confirmation=confirmation,
            )

    def get_withdrawal_acknowledgement(
        self,
        *,
        user_id: str,
        purchase_id: str,
    ) -> DbBillingWithdrawalRequest:
        with self.db.session() as session:
            owned_record = session.execute(
                select(
                    DbBillingWithdrawalRequest,
                    DbCreditPurchase,
                    DbBillingContractConfirmation,
                )
                .join(
                    DbCreditPurchase,
                    DbCreditPurchase.id == DbBillingWithdrawalRequest.purchase_id,
                )
                .join(
                    DbBillingContractConfirmation,
                    DbBillingContractConfirmation.purchase_id == DbBillingWithdrawalRequest.purchase_id,
                )
                .where(
                    DbBillingWithdrawalRequest.purchase_id == purchase_id,
                    DbCreditPurchase.user_id == user_id,
                )
                .limit(1)
            ).one_or_none()
        if owned_record is None:
            raise BillingConsumerRecordNotFoundError(
                "Withdrawal acknowledgement not found",
            )
        withdrawal, purchase, confirmation = owned_record
        self._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
        return cast(DbBillingWithdrawalRequest, withdrawal)

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if normalized != value or not _IDEMPOTENCY_RE.fullmatch(normalized):
            raise BillingConsumerRecordValidationError(
                "Invalid Idempotency-Key",
            )
        return normalized

    @staticmethod
    def _advisory_lock_key(value: str) -> int:
        return int.from_bytes(
            hashlib.sha256(value.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )

    @staticmethod
    def _verify_withdrawal(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase | None = None,
        confirmation: DbBillingContractConfirmation | None = None,
    ) -> None:
        if (purchase is None) != (confirmation is None):
            raise BillingConsumerRecordConflictError(
                "Withdrawal purchase or contract evidence is unavailable",
            )
        if type(withdrawal.schema_version) is int and withdrawal.schema_version == _WITHDRAWAL_SCHEMA_VERSION_V1:
            BillingConsumerRecordStore._verify_withdrawal_v1(
                withdrawal,
                purchase=purchase,
                confirmation=confirmation,
            )
            return
        raise BillingConsumerRecordConflictError(
            "Withdrawal acknowledgement schema version is unsupported",
        )

    @staticmethod
    def _verify_withdrawal_v1(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase | None = None,
        confirmation: DbBillingContractConfirmation | None = None,
    ) -> None:
        request_snapshot = withdrawal.request_snapshot
        if not isinstance(request_snapshot, dict):
            raise BillingConsumerRecordConflictError(
                "Withdrawal request snapshot is invalid",
            )
        try:
            normalized_idempotency_key = BillingConsumerRecordStore._validate_idempotency_key(
                withdrawal.idempotency_key,
            )
        except (
            AttributeError,
            BillingConsumerRecordValidationError,
        ) as exc:
            raise BillingConsumerRecordConflictError(
                "Withdrawal acknowledgement identity is invalid",
            ) from exc
        request_bytes = _canonical_json_bytes(request_snapshot)
        if (
            not isinstance(withdrawal.request_bytes, bytes)
            or withdrawal.request_bytes != request_bytes
            or _sha256(withdrawal.request_bytes) != withdrawal.request_sha256
            or not isinstance(withdrawal.acknowledgement_bytes, bytes)
            or _sha256(withdrawal.acknowledgement_bytes) != withdrawal.acknowledgement_sha256
        ):
            raise BillingConsumerRecordConflictError(
                "Withdrawal acknowledgement digest does not match",
            )
        if (
            type(withdrawal.schema_version) is not int
            or withdrawal.schema_version != _WITHDRAWAL_SCHEMA_VERSION_V1
            or not isinstance(withdrawal.purchase_id, str)
            or not _PURCHASE_ID_RE.fullmatch(withdrawal.purchase_id)
            or withdrawal.locale not in {"el", "en"}
            or withdrawal.status != _WITHDRAWAL_V1_STATUS
            or normalized_idempotency_key != withdrawal.idempotency_key
            or type(withdrawal.submitted_at) is not int
            or withdrawal.submitted_at <= 0
            or withdrawal.acknowledgement_mime_type != "application/json; charset=utf-8"
            or withdrawal.acknowledgement_filename != f"gsubs-withdrawal-{withdrawal.purchase_id}.json"
            or type(withdrawal.available_at) is not int
            or type(withdrawal.created_at) is not int
            or type(withdrawal.financial_retention_until) is not int
            or withdrawal.available_at != withdrawal.submitted_at
            or withdrawal.created_at != withdrawal.submitted_at
            or withdrawal.financial_retention_until <= withdrawal.submitted_at
            or not isinstance(withdrawal.request_sha256, str)
            or not _SHA256_RE.fullmatch(withdrawal.request_sha256)
            or not isinstance(
                withdrawal.acknowledgement_sha256,
                str,
            )
            or not _SHA256_RE.fullmatch(
                withdrawal.acknowledgement_sha256,
            )
            or withdrawal.id
            != _deterministic_id(
                "gsubs-withdrawal",
                f"{withdrawal.purchase_id}:{withdrawal.submitted_at}",
            )
        ):
            raise BillingConsumerRecordConflictError(
                "Withdrawal acknowledgement identity is invalid",
            )

        electronic_means = request_snapshot.get(
            "confirmation_electronic_means",
        )
        concluded_at = request_snapshot.get("contract_concluded_at")
        timeliness_assessment_status = request_snapshot.get(
            "timeliness_assessment_status",
        )
        confirmed_name = request_snapshot.get("confirmed_name")
        if (
            set(request_snapshot)
            != {
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
            or request_snapshot.get("schema_version") != withdrawal.schema_version
            or request_snapshot.get("request_type") != "consumer_contract_withdrawal"
            or request_snapshot.get("purchase_id") != withdrawal.purchase_id
            or request_snapshot.get("locale") != withdrawal.locale
            or request_snapshot.get("statement")
            != BillingConsumerRecordStore._withdrawal_statement_v1(
                withdrawal.locale,
                purchase_id=withdrawal.purchase_id,
            )
            or not isinstance(confirmed_name, str)
            or confirmed_name.strip() != confirmed_name
            or not confirmed_name
            or len(confirmed_name) > 100
            or not isinstance(electronic_means, dict)
            or set(electronic_means) != {"type", "address", "delivery_status"}
            or electronic_means.get("type") != "email"
            or electronic_means.get("delivery_status") != "not_sent_transactional_channel_not_ready"
            or not isinstance(electronic_means.get("address"), str)
            or electronic_means["address"].strip() != electronic_means["address"]
            or len(electronic_means["address"]) > 255
            or not _EMAIL_RE.fullmatch(electronic_means["address"])
            or request_snapshot.get("submitted_at") != withdrawal.submitted_at
            or isinstance(concluded_at, bool)
            or not isinstance(concluded_at, int)
            or concluded_at <= 0
            or withdrawal.submitted_at < concluded_at
            or timeliness_assessment_status != _WITHDRAWAL_V1_TIMELINESS_ASSESSMENT_STATUS
            or request_snapshot.get("status") != withdrawal.status
            or request_snapshot.get(
                "automatic_stripe_refund_executed",
            )
            is not False
            or request_snapshot.get(
                "automatic_aade_adjustment_executed",
            )
            is not False
        ):
            raise BillingConsumerRecordConflictError(
                "Withdrawal request conflicts with its identity",
            )

        try:
            acknowledgement = json.loads(
                withdrawal.acknowledgement_bytes,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BillingConsumerRecordConflictError(
                "Withdrawal acknowledgement content is invalid",
            ) from exc
        expected_acknowledgement = {
            **request_snapshot,
            "document_type": "gsubs_withdrawal_acknowledgement",
            "request_sha256": withdrawal.request_sha256,
            "receipt_notice": BillingConsumerRecordStore._receipt_notice_v1(
                withdrawal.locale,
            ),
        }
        if (
            not isinstance(acknowledgement, dict)
            or acknowledgement != expected_acknowledgement
            or withdrawal.acknowledgement_bytes
            != _canonical_json_bytes(
                expected_acknowledgement,
                pretty=True,
            )
        ):
            raise BillingConsumerRecordConflictError(
                "Withdrawal acknowledgement conflicts with request evidence",
            )

        if confirmation is not None:
            if purchase is None:
                raise BillingConsumerRecordConflictError(
                    "Withdrawal purchase evidence is unavailable",
                )
            verify_contract_confirmation(
                confirmation,
                purchase=purchase,
            )
            if (
                confirmation.purchase_id != withdrawal.purchase_id
                or concluded_at != confirmation.contract_concluded_at
                or withdrawal.financial_retention_until < confirmation.financial_retention_until
            ):
                raise BillingConsumerRecordConflictError(
                    "Withdrawal conflicts with contract confirmation",
                )
        if purchase is not None and (purchase.id != withdrawal.purchase_id):
            raise BillingConsumerRecordConflictError(
                "Withdrawal conflicts with purchase evidence",
            )

    @staticmethod
    def _withdrawal_result(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase | None = None,
        confirmation: DbBillingContractConfirmation | None = None,
    ) -> WithdrawalResult:
        BillingConsumerRecordStore._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
        return WithdrawalResult(
            withdrawal_id=withdrawal.id,
            purchase_id=withdrawal.purchase_id,
            status=withdrawal.status,
            submitted_at=withdrawal.submitted_at,
            timeliness_assessment_status=str(
                withdrawal.request_snapshot.get(
                    "timeliness_assessment_status",
                    "",
                ),
            ),
            acknowledgement_sha256=withdrawal.acknowledgement_sha256,
        )

    @staticmethod
    def _assert_withdrawal_replay_equivalent(
        withdrawal: DbBillingWithdrawalRequest,
        *,
        purchase: DbCreditPurchase,
        confirmation: DbBillingContractConfirmation,
        locale: str,
        normalized_name: str,
        normalized_email: str,
        conflict_message: str,
    ) -> None:
        BillingConsumerRecordStore._verify_withdrawal(
            withdrawal,
            purchase=purchase,
            confirmation=confirmation,
        )
        request_snapshot = withdrawal.request_snapshot
        if (
            withdrawal.purchase_id != purchase.id
            or confirmation.purchase_id != purchase.id
            or withdrawal.locale != locale
            or request_snapshot.get("locale") != locale
            or request_snapshot.get("statement")
            != BillingConsumerRecordStore._withdrawal_statement_v1(
                locale,
                purchase_id=purchase.id,
            )
            or request_snapshot.get("confirmed_name") != normalized_name
            or request_snapshot.get("confirmation_electronic_means")
            != {
                "type": "email",
                "address": normalized_email,
                "delivery_status": (
                    "not_sent_transactional_channel_not_ready"
                ),
            }
            or request_snapshot.get("contract_concluded_at")
            != confirmation.contract_concluded_at
        ):
            raise BillingConsumerRecordConflictError(conflict_message)

    @staticmethod
    def _withdrawal_statement(locale: str, *, purchase_id: str) -> str:
        if WITHDRAWAL_SCHEMA_VERSION != _WITHDRAWAL_SCHEMA_VERSION_V1:
            raise BillingConsumerRecordValidationError(
                "Withdrawal acknowledgement schema version is unsupported",
            )
        return BillingConsumerRecordStore._withdrawal_statement_v1(
            locale,
            purchase_id=purchase_id,
        )

    @staticmethod
    def _withdrawal_statement_v1(
        locale: str,
        *,
        purchase_id: str,
    ) -> str:
        if locale == "el":
            return f"Δηλώνω ότι υπαναχωρώ από τη σύμβαση αγοράς GSUBS credits με αναγνωριστικό {purchase_id}."
        return f"I give notice that I withdraw from the GSUBS credit purchase contract identified by {purchase_id}."

    @staticmethod
    def _receipt_notice(locale: str) -> str:
        if WITHDRAWAL_SCHEMA_VERSION != _WITHDRAWAL_SCHEMA_VERSION_V1:
            raise BillingConsumerRecordValidationError(
                "Withdrawal acknowledgement schema version is unsupported",
            )
        return BillingConsumerRecordStore._receipt_notice_v1(locale)

    @staticmethod
    def _receipt_notice_v1(locale: str) -> str:
        if locale == "el":
            return (
                "Το αίτημα παραλήφθηκε και εκκρεμεί χειροκίνητη εξέταση. Δεν "
                "εκτελέστηκε αυτόματα επιστροφή Stripe ή διόρθωση ΑΑΔΕ."
            )
        return (
            "The request was received and is pending manual review. No Stripe "
            "refund or AADE adjustment was executed automatically."
        )


def verify_withdrawal_record(
    withdrawal: DbBillingWithdrawalRequest,
    *,
    purchase: DbCreditPurchase,
    confirmation: DbBillingContractConfirmation,
) -> None:
    """Public strict validator shared by account access and GDPR export."""
    BillingConsumerRecordStore._verify_withdrawal(
        withdrawal,
        purchase=purchase,
        confirmation=confirmation,
    )
