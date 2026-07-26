"""Immutable Stripe payment snapshots and pending manual AADE records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from backend.app.db.models import DbBillingInvoice, DbCreditPurchase
from backend.app.services.financial_records import financial_retention_deadline

AADE_SERVICE_CODE = "4"
AADE_SERVICE_NAME = "GSUBS Credits"
AADE_GREEK_B2C_DOCUMENT_TYPE = "11.2"
AADE_GREEK_B2C_SERIES = "0"
AADE_GREEK_B2C_PAYMENT_METHOD = "domestic_professional_payment_account"
ACCOUNTING_METHOD = "manual_aade_etimologio"
STRIPE_PRODUCT_TAX_CODE = "txcd_10103001"
VAT_RATE_PERCENT = 24
_REQUIRED_CUSTOMER_FIELDS = ("name", "email", "country", "city", "postal_code")


@dataclass(frozen=True, slots=True)
class PaidFinancialRecord:
    payment_snapshot: dict[str, Any]
    customer_snapshot: dict[str, Any]
    tax_snapshot: dict[str, Any]
    invoice_snapshot: dict[str, Any]
    invoice_status: str
    retention_until: int


def build_paid_financial_record(
    *,
    purchase: DbCreditPurchase,
    checkout: dict[str, Any],
    stripe_event_created: int,
    livemode: bool,
) -> PaidFinancialRecord:
    """Build the write-once accounting record from one signed Checkout event."""
    if isinstance(stripe_event_created, bool) or stripe_event_created <= 0:
        raise ValueError("Stripe event timestamp is invalid")

    customer_details = _mapping(checkout.get("customer_details"))
    address = _mapping(customer_details.get("address"))
    country = _clean_string(address.get("country"))
    customer_snapshot: dict[str, Any] = {
        "source": "stripe_checkout_session",
        "customer_type": "individual",
        "name": _clean_string(
            customer_details.get("individual_name")
            or customer_details.get("name")
            or customer_details.get("business_name")
        ),
        "email": _clean_string(customer_details.get("email")),
        "country": country.upper() if country else None,
        "city": _clean_string(address.get("city")),
        "postal_code": _clean_string(address.get("postal_code")),
        "line1": _clean_string(address.get("line1")),
        "line2": _clean_string(address.get("line2")),
        "state": _clean_string(address.get("state")),
    }
    missing = [field for field in _REQUIRED_CUSTOMER_FIELDS if not customer_snapshot[field]]
    customer_status = "ready_for_manual_issue" if not missing else "manual_review_required"
    customer_snapshot["missing_required_fields"] = missing
    customer_snapshot["status"] = customer_status

    gross_cents = int(purchase.amount_eur_cents)
    net_cents = _inclusive_net_cents(
        gross_cents,
        vat_rate_percent=VAT_RATE_PERCENT,
    )
    vat_cents = gross_cents - net_cents
    automatic_tax = _mapping(checkout.get("automatic_tax"))
    if automatic_tax.get("enabled") is True:
        raise ValueError("Stripe Automatic Tax is incompatible with the approved manual tax workflow")
    total_details = _mapping(checkout.get("total_details"))
    stripe_amount_tax_cents = _optional_nonnegative_int(total_details.get("amount_tax"))
    if stripe_amount_tax_cents not in {None, 0}:
        raise ValueError("Stripe tax totals are incompatible with the approved manual tax workflow")
    tax_snapshot = {
        "accounting_method": ACCOUNTING_METHOD,
        "customer_type": "individual",
        "tax_id_collection": "not_requested",
        "tax_ids": _tax_ids(customer_details.get("tax_ids")),
        "automatic_tax_enabled": automatic_tax.get("enabled") is True,
        "automatic_tax_status": _clean_string(automatic_tax.get("status")),
        "stripe_amount_tax_cents": stripe_amount_tax_cents,
        "stripe_product_tax_code": STRIPE_PRODUCT_TAX_CODE,
        "tax_behavior": "inclusive",
        "vat_rate_percent": VAT_RATE_PERCENT,
        "gross_amount_cents": gross_cents,
        "net_amount_cents": net_cents,
        "vat_amount_cents": vat_cents,
    }
    payment_snapshot = {
        "source": "stripe_checkout_session",
        "checkout_session_id": _stripe_id(checkout.get("id")),
        "payment_intent_id": _stripe_id(checkout.get("payment_intent")),
        "stripe_customer_id": _stripe_id(checkout.get("customer")),
        "stripe_event_created": stripe_event_created,
        "livemode": livemode,
        "amount_paid_cents": gross_cents,
        "currency": str(purchase.currency).lower(),
        "payment_status": _clean_string(checkout.get("payment_status")),
    }
    invoice_snapshot = {
        "service_code": AADE_SERVICE_CODE,
        "service_name": AADE_SERVICE_NAME,
        "expected_document_type": AADE_GREEK_B2C_DOCUMENT_TYPE,
        "expected_series": AADE_GREEK_B2C_SERIES,
        "expected_payment_method": AADE_GREEK_B2C_PAYMENT_METHOD,
        "package_key": purchase.package_key,
        "credits": purchase.credits,
        "currency": str(purchase.currency).lower(),
        "gross_amount_cents": gross_cents,
        "net_amount_cents": net_cents,
        "vat_rate_percent": VAT_RATE_PERCENT,
        "vat_amount_cents": vat_cents,
        "customer_status": customer_status,
        "source_purchase_id": purchase.id,
    }
    return PaidFinancialRecord(
        payment_snapshot=payment_snapshot,
        customer_snapshot=customer_snapshot,
        tax_snapshot=tax_snapshot,
        invoice_snapshot=invoice_snapshot,
        invoice_status=(
            "pending_manual_issue" if customer_status == "ready_for_manual_issue" else "manual_review_required"
        ),
        retention_until=financial_retention_deadline(stripe_event_created),
    )


def new_pending_invoice(
    *,
    purchase_id: str,
    record: PaidFinancialRecord,
    created_at: int,
) -> DbBillingInvoice:
    """Create the deterministic one-to-one manual document placeholder."""
    digest = hashlib.sha256(f"gsubs-aade-invoice:v1:{purchase_id}".encode()).hexdigest()
    return DbBillingInvoice(
        id=digest[:32],
        purchase_id=purchase_id,
        provider="aade_etimologio",
        document_kind="retail_service_receipt",
        document_status=record.invoice_status,
        aade_document_type=None,
        aade_series=None,
        aade_aa=None,
        aade_mark=None,
        issued_at=None,
        recorded_by_user_id=None,
        recorded_at=None,
        document_snapshot=record.invoice_snapshot,
        financial_retention_until=record.retention_until,
        created_at=created_at,
        updated_at=created_at,
    )


def _inclusive_net_cents(gross_cents: int, *, vat_rate_percent: int) -> int:
    if gross_cents <= 0 or vat_rate_percent <= 0:
        raise ValueError("Gross amount and VAT rate must be positive")
    denominator = 100 + vat_rate_percent
    return (gross_cents * 100 + denominator // 2) // denominator


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _stripe_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return ""


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Stripe tax total is invalid")
    return int(value)


def _tax_ids(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tax_id_type = _clean_string(item.get("type"))
        tax_id_value = _clean_string(item.get("value"))
        if tax_id_type and tax_id_value:
            normalized.append({"type": tax_id_type, "value": tax_id_value})
    return normalized
