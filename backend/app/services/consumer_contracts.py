"""Versioned, content-addressed consumer-contract disclosures for paid credits.

The registry is deliberately code-owned and immutable. Any wording change must
create a new version and therefore a new digest; existing purchase snapshots
continue to contain the exact text that the customer accepted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ConsumerLocale = Literal["el", "en"]

CONSUMER_CONTRACT_SCHEMA_VERSION = 1
CONSUMER_POLICY_VERSION = "2026-08-28-owner-approved-v2"
TERMS_VERSION = "2026-08-28-owner-approved-v2"
WITHDRAWAL_NOTICE_VERSION = "2026-08-28-owner-approved-v2"
CONFIRMATION_TEMPLATE_VERSION = "2026-08-28-owner-approved-v2"
CONSUMER_CONTRACT_CLASSIFICATION = "digital_service_with_prepaid_internal_units"
CONSUMER_CONTRACT_STATUS = "approved"
DURABLE_CONFIRMATION_CHANNEL_STATUS = "approved"
ADJUSTMENT_WORKFLOW_STATUS = "approved"
# The owner-approved operational workflow remains deliberately manual: every
# refund and AADE adjustment needs an explicit human decision and is recorded
# append-only. No browser action can issue a refund or tax document by itself.
ADJUSTMENT_WORKFLOW_IMPLEMENTED = True
CONTRACT_CONFIRMATION_DELIVERY_CHANNEL = "account_vault"
CONTRACT_CONFIRMATION_DELIVERY_STATUS = "available_approved"
APPROVED_CONTRACT_CONFIRMATION_DELIVERY_STATUS = "available_approved"
# Each entry binds the owner-approved version tuple and canonical localized
# disclosure digest. Any wording or trader-identity change invalidates it.
CONSUMER_CONTRACT_APPROVAL_MANIFEST: dict[str, dict[str, str]] = {
    "el": {
        "locale": "el",
        "policy_version": "2026-08-28-owner-approved-v2",
        "terms_version": "2026-08-28-owner-approved-v2",
        "withdrawal_notice_version": "2026-08-28-owner-approved-v2",
        "confirmation_template_version": "2026-08-28-owner-approved-v2",
        "disclosure_id": "gsubs-b2c-el-2026-08-28-owner-approved-v2",
        "disclosure_sha256": "d49507e518a22e4f9187f61b8a88b77f0832831924bbb8b95b6b469115a80ac3",
    },
    "en": {
        "locale": "en",
        "policy_version": "2026-08-28-owner-approved-v2",
        "terms_version": "2026-08-28-owner-approved-v2",
        "withdrawal_notice_version": "2026-08-28-owner-approved-v2",
        "confirmation_template_version": "2026-08-28-owner-approved-v2",
        "disclosure_id": "gsubs-b2c-en-2026-08-28-owner-approved-v2",
        "disclosure_sha256": "4160423df038e77420722453c563860351fa4f8608d4aa7e89196f615a27df7c",
    },
}
PAID_CREDIT_LEGAL_PUBLICATION_IDENTITY: object = json.loads(
    Path(__file__).with_name("paid_credit_legal_publication.json").read_text(encoding="utf-8")
)
_TRADER_DETAILS = {
    "legal_name": "Ascentia G.P.",
    "legal_form": "General Partnership (O.E.)",
    "trading_name": "Ascentia",
    "service": "GSUBS",
    "tax_identification_number": "802523620",
    "vat_id": "EL802523620",
    "commercial_register": "General Commercial Registry (GEMI)",
    "commercial_registration_number": "177974203000",
    "euid": "ELGEMI.177974203000",
    "address_line_1": "Agias Varvaras 4",
    "postal_code": "16452",
    "city": "Argiroupoli, Athens",
    "country": "GR",
    "support_email": "info@ascentia-gp.com",
    "support_phone": "+30 698 756 4060",
    "website": "https://ascentia-gp.com/",
}


class ConsumerContractValidationError(ValueError):
    """The browser did not accept the current canonical consumer contract."""


@dataclass(frozen=True, slots=True)
class ConsumerContractAcceptance:
    """Untrusted browser values that must match the canonical registry exactly."""

    catalog_version: str
    disclosure_id: str
    disclosure_sha256: str
    locale: ConsumerLocale
    policy_version: str
    terms_version: str
    withdrawal_notice_version: str
    terms_accepted: bool
    immediate_performance_requested: bool
    withdrawal_consequences_acknowledged: bool


@dataclass(frozen=True, slots=True)
class _Disclosure:
    locale: ConsumerLocale
    disclosure_id: str
    title: str
    service_description: str
    credit_description: str
    purchase_terms: str
    delivery_timing: str
    validity_and_transfer: str
    functionality: str
    compatibility: str
    withdrawal_notice: str
    manual_review_notice: str
    terms_acceptance: str
    immediate_performance_request: str
    withdrawal_consequences_acknowledgement: str


_DISCLOSURES: tuple[_Disclosure, ...] = (
    _Disclosure(
        locale="el",
        disclosure_id="gsubs-b2c-el-2026-08-28-owner-approved-v2",
        title="Προσυμβατικές πληροφορίες αγοράς GSUBS credits",
        service_description=(
            "Το GSUBS παρέχει ψηφιακή υπηρεσία επεξεργασίας αρχείων βίντεο και "
            "ήχου για απομαγνητοφώνηση, δημιουργία υποτίτλων, προεπισκόπηση και "
            "εξαγωγή αποτελεσμάτων."
        ),
        credit_description=(
            "Τα credits είναι προπληρωμένες εσωτερικές μονάδες που "
            "χρησιμοποιούνται αποκλειστικά για την πληρωμή της ψηφιακής "
            "υπηρεσίας επεξεργασίας GSUBS. Δεν αποτελούν από μόνα τους "
            "downloadable ψηφιακό περιεχόμενο."
        ),
        purchase_terms=(
            "Η online αγορά είναι διαθέσιμη μόνο σε καταναλωτές με διεύθυνση "
            "χρέωσης στην Ελλάδα. Είναι εφάπαξ, χωρίς συνδρομή ή αυτόματη "
            "ανανέωση. Το επιλεγμένο πακέτο, ο αριθμός credits και η συνολική "
            "τελική τιμή σε ευρώ, με ΦΠΑ 24%, εμφανίζονται πριν από την εντολή "
            "πληρωμής. Ένα επιλέξιμο μέσο πληρωμής προεγκρίνεται προσωρινά στο "
            "Stripe Checkout. Η είσπραξη ολοκληρώνεται και τα credits "
            "πιστώνονται μόνο αφού το "
            "GSUBS επιβεβαιώσει από το υπογεγραμμένο Stripe συμβάν την ελληνική "
            "διεύθυνση χρέωσης και τα ακριβή στοιχεία της αγοράς. Αν ο έλεγχος "
            "αποτύχει, η προέγκριση ακυρώνεται· η προσωρινή δέσμευση μπορεί να "
            "παραμένει ορατή για διάστημα που καθορίζει ο εκδότης ή ο πάροχος "
            "του μέσου πληρωμής."
        ),
        delivery_timing=(
            "Μετά την επιβεβαίωση της πληρωμής και τη δημιουργία της "
            "επιβεβαίωσης σύμβασης, τα credits πιστώνονται στον λογαριασμό. Η "
            "επεξεργασία αρχίζει μόνο όταν ο χρήστης υποβάλει ξεχωριστά εργασία."
        ),
        validity_and_transfer=(
            "Το τρέχον τεχνικό σύστημα δεν εφαρμόζει αυτόματη λήξη των credits, "
            "δεν παρέχει μεταφορά τους σε άλλον λογαριασμό και δεν παρέχει "
            "μηχανισμό εξαργύρωσής τους σε μετρητά. Τα υποχρεωτικά δικαιώματα "
            "του καταναλωτή δεν περιορίζονται."
        ),
        functionality=(
            "Η υπηρεσία καταναλώνει credits σύμφωνα με τη διάρκεια και τη "
            "λειτουργία επεξεργασίας που εμφανίζονται στον κατάλογο τιμολόγησης."
        ),
        compatibility=(
            "Απαιτούνται υποστηριζόμενο πρόγραμμα περιήγησης, σύνδεση στο "
            "διαδίκτυο και αρχείο που περνά τους δημοσιευμένους περιορισμούς "
            "μορφής, μεγέθους και διάρκειας."
        ),
        withdrawal_notice=(
            "Ο καταναλωτής μπορεί να υπαναχωρήσει εντός 14 ημερών από τη σύναψη "
            "της σύμβασης. Αν έχει ζητήσει να αρχίσει η υπηρεσία μέσα σε αυτό "
            "το διάστημα και έχει ήδη παρασχεθεί μέρος της, μπορεί να οφείλεται "
            "αναλογικό ποσό για το μέρος που παρασχέθηκε. Το δικαίωμα χάνεται "
            "μόνο μετά την πλήρη εκτέλεση της υπηρεσίας, όταν συντρέχουν οι "
            "νόμιμες προϋποθέσεις."
        ),
        manual_review_notice=(
            "Δεν παρέχεται αυτόματη επιστροφή ή προαιρετική επιστροφή μόνο "
            "επειδή ο χρήστης άλλαξε γνώμη ή δεν χρησιμοποίησε τα credits. "
            "Αυτό δεν περιορίζει δικαιώματα που επιβάλλει ο νόμος, όπως όπου "
            "ισχύουν η υπαναχώρηση, η μη σύμφωνη παροχή ή η διπλή ή μη "
            "εξουσιοδοτημένη χρέωση. Κάθε αίτημα καταγράφεται και εξετάζεται "
            "χειροκίνητα. Αν εγκριθεί, η επιστροφή Stripe και το απαιτούμενο "
            "διορθωτικό παραστατικό ΑΑΔΕ εκτελούνται και καταχωρίζονται "
            "χειροκίνητα· η υποβολή του αιτήματος δεν εκτελεί καμία από αυτές "
            "τις ενέργειες αυτόματα."
        ),
        terms_acceptance=(
            "Έχω διαβάσει και αποδέχομαι τους Όρους Πώλησης και τις προσυμβατικές πληροφορίες για το επιλεγμένο πακέτο."
        ),
        immediate_performance_request=(
            "Ζητώ ρητά να αρχίσει η παροχή της ψηφιακής υπηρεσίας GSUBS πριν "
            "λήξει η προθεσμία υπαναχώρησης των 14 ημερών."
        ),
        withdrawal_consequences_acknowledgement=(
            "Κατανοώ ότι, αν υπαναχωρήσω αφού αρχίσει η παροχή, μπορεί να "
            "οφείλω αναλογικά για ό,τι παρασχέθηκε έως τότε και ότι το δικαίωμα "
            "χάνεται μόνο μετά την πλήρη εκτέλεση της σύμβασης, όταν "
            "συντρέχουν οι νόμιμες προϋποθέσεις."
        ),
    ),
    _Disclosure(
        locale="en",
        disclosure_id="gsubs-b2c-en-2026-08-28-owner-approved-v2",
        title="Pre-contract information for a GSUBS credit purchase",
        service_description=(
            "GSUBS provides a digital service that processes video and audio "
            "files for transcription, caption creation, preview, and export."
        ),
        credit_description=(
            "Credits are prepaid internal units used exclusively to pay for "
            "the GSUBS digital processing service. They are not, by themselves, "
            "downloadable digital content."
        ),
        purchase_terms=(
            "Online purchase is available only to consumers with a billing "
            "address in Greece. It is one-off, with no subscription or "
            "automatic renewal. The selected package, number of credits, and "
            "total final price in euros, including 24% VAT, are shown before "
            "the order with an obligation to pay. An eligible payment method "
            "is temporarily authorized in Stripe Checkout. Capture and credit "
            "delivery occur only after GSUBS validates the Greek billing "
            "address and exact purchase evidence from the signed Stripe event. "
            "If validation fails, the authorization is canceled; the temporary "
            "hold may remain visible for a period determined by the payment "
            "method provider or issuer."
        ),
        delivery_timing=(
            "After payment is confirmed and the contract confirmation is "
            "created, credits are added to the account. Processing begins only "
            "when the user separately submits a job."
        ),
        validity_and_transfer=(
            "The current technical system does not automatically expire "
            "credits, does not provide a way to transfer them to another "
            "account, and does not provide cash redemption. Mandatory consumer "
            "rights are not restricted."
        ),
        functionality=(
            "The service consumes credits according to the processing duration "
            "and function shown in the pricing catalog."
        ),
        compatibility=(
            "A supported browser, an internet connection, and a file that "
            "passes the published format, size, and duration limits are required."
        ),
        withdrawal_notice=(
            "A consumer may withdraw within 14 days after the contract is "
            "concluded. If the consumer requested that the service begin during "
            "that period and part of the service has already been supplied, a "
            "proportionate amount may be due for the supplied part. The right is "
            "lost only after full performance of the service when the legal "
            "conditions are met."
        ),
        manual_review_notice=(
            "There is no automatic refund or discretionary refund merely "
            "because the user changed their mind or did not use the credits. "
            "This does not restrict rights required by law, including where "
            "applicable withdrawal, non-conforming performance, or a duplicate "
            "or unauthorized charge. Every request is recorded and reviewed "
            "manually. If approved, the Stripe refund and required AADE "
            "adjustment document are performed and recorded manually; "
            "submitting the request does not execute either action automatically."
        ),
        terms_acceptance=(
            "I have read and accept the Terms of Sale and the pre-contract information for the selected package."
        ),
        immediate_performance_request=(
            "I expressly request that the GSUBS digital service begin before the 14-day withdrawal period has expired."
        ),
        withdrawal_consequences_acknowledgement=(
            "I understand that, if I withdraw after performance begins, I may "
            "owe a proportionate amount for what was supplied and that the "
            "right is lost only after full performance of the contract when "
            "the legal conditions are met."
        ),
    ),
)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def paid_credit_legal_publication_approval_sha256() -> str:
    """Bind the public Terms route to the exact backend approval manifest."""
    payload = {
        "schema_version": 1,
        "public_terms_route": "/terms",
        "terms_version": TERMS_VERSION,
        "consumer_contract_approval_manifest": (CONSUMER_CONTRACT_APPROVAL_MANIFEST),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def paid_credit_legal_publication_is_approved() -> bool:
    """Require one exact non-draft identity shared with the frontend build."""
    identity = PAID_CREDIT_LEGAL_PUBLICATION_IDENTITY
    if not isinstance(identity, dict):
        return False
    if set(identity) != {
        "schema_version",
        "status",
        "public_terms_route",
        "terms_version",
        "approval_identity_sha256",
    }:
        return False
    terms_version = identity.get("terms_version")
    approval_digest = identity.get("approval_identity_sha256")
    return (
        type(identity.get("schema_version")) is int
        and identity["schema_version"] == 1
        and identity.get("status") == "approved"
        and identity.get("public_terms_route") == "/terms"
        and isinstance(terms_version, str)
        and terms_version == TERMS_VERSION
        and "draft" not in terms_version.casefold()
        and isinstance(approval_digest, str)
        and approval_digest == paid_credit_legal_publication_approval_sha256()
    )


def _registered_disclosure(locale: str) -> _Disclosure:
    for disclosure in _DISCLOSURES:
        if disclosure.locale == locale:
            return disclosure
    raise ConsumerContractValidationError("Unsupported consumer-contract locale")


def public_consumer_contract(locale: str) -> dict[str, Any]:
    """Return the exact current disclosure and its content-addressed identity."""
    disclosure = _registered_disclosure(locale)
    content = {
        "title": disclosure.title,
        "service_description": disclosure.service_description,
        "credit_description": disclosure.credit_description,
        "purchase_terms": disclosure.purchase_terms,
        "delivery_timing": disclosure.delivery_timing,
        "validity_and_transfer": disclosure.validity_and_transfer,
        "functionality": disclosure.functionality,
        "compatibility": disclosure.compatibility,
        "withdrawal_notice": disclosure.withdrawal_notice,
        "manual_review_notice": disclosure.manual_review_notice,
    }
    acceptances = {
        "terms": disclosure.terms_acceptance,
        "immediate_performance": disclosure.immediate_performance_request,
        "withdrawal_consequences": disclosure.withdrawal_consequences_acknowledgement,
    }
    canonical = {
        "schema_version": CONSUMER_CONTRACT_SCHEMA_VERSION,
        "status": CONSUMER_CONTRACT_STATUS,
        "launch_review_status": {
            "consumer_policy": CONSUMER_CONTRACT_STATUS,
            "durable_confirmation_channel": (DURABLE_CONFIRMATION_CHANNEL_STATUS),
            "adjustment_workflow": ADJUSTMENT_WORKFLOW_STATUS,
            "adjustment_workflow_implemented": (ADJUSTMENT_WORKFLOW_IMPLEMENTED),
            "contract_confirmation_delivery": (CONTRACT_CONFIRMATION_DELIVERY_STATUS),
        },
        "classification": CONSUMER_CONTRACT_CLASSIFICATION,
        "disclosure_id": disclosure.disclosure_id,
        "locale": disclosure.locale,
        "policy_version": CONSUMER_POLICY_VERSION,
        "terms_version": TERMS_VERSION,
        "withdrawal_notice_version": WITHDRAWAL_NOTICE_VERSION,
        "confirmation_template_version": CONFIRMATION_TEMPLATE_VERSION,
        "contract_confirmation_delivery": {
            "channel": CONTRACT_CONFIRMATION_DELIVERY_CHANNEL,
            "status": CONTRACT_CONFIRMATION_DELIVERY_STATUS,
        },
        "terms_url": "/terms",
        "withdrawal_url": "/account/billing",
        "model_withdrawal_form_url": "/terms#withdrawal",
        "trader": dict(_TRADER_DETAILS),
        "content": content,
        "required_acceptances": acceptances,
    }
    return {
        **canonical,
        "disclosure_sha256": hashlib.sha256(_canonical_json(canonical)).hexdigest(),
    }


def consumer_contract_registry_is_approved() -> bool:
    """Require every code-owned legal/operational launch review to be approved."""
    statuses_are_approved = (
        CONSUMER_CONTRACT_STATUS == "approved"
        and DURABLE_CONFIRMATION_CHANNEL_STATUS == "approved"
        and ADJUSTMENT_WORKFLOW_STATUS == "approved"
        and ADJUSTMENT_WORKFLOW_IMPLEMENTED is True
        and CONTRACT_CONFIRMATION_DELIVERY_STATUS == APPROVED_CONTRACT_CONFIRMATION_DELIVERY_STATUS
    )
    if not statuses_are_approved:
        return False
    for locale in ("el", "en"):
        canonical = public_consumer_contract(locale)
        approval_identity = (
            canonical["policy_version"],
            canonical["terms_version"],
            canonical["withdrawal_notice_version"],
            canonical["confirmation_template_version"],
            canonical["disclosure_id"],
        )
        if any("draft" in str(value).casefold() for value in approval_identity):
            return False
        expected_manifest_entry = {
            "locale": locale,
            "policy_version": str(canonical["policy_version"]),
            "terms_version": str(canonical["terms_version"]),
            "withdrawal_notice_version": str(
                canonical["withdrawal_notice_version"],
            ),
            "confirmation_template_version": str(
                canonical["confirmation_template_version"],
            ),
            "disclosure_id": str(canonical["disclosure_id"]),
            "disclosure_sha256": str(
                canonical["disclosure_sha256"],
            ),
        }
        if CONSUMER_CONTRACT_APPROVAL_MANIFEST.get(locale) != expected_manifest_entry:
            return False
    return set(CONSUMER_CONTRACT_APPROVAL_MANIFEST) == {"el", "en"} and paid_credit_legal_publication_is_approved()


def assert_consumer_contract_registry_approved() -> None:
    """Fail startup when environment flags try to activate draft wording."""
    if not consumer_contract_registry_is_approved():
        raise RuntimeError(
            "Paid credit Checkout remains fail closed because the canonical "
            "consumer policy, durable confirmation channel, adjustment "
            "workflow, artifact delivery status, or exact public Terms "
            "identity is not approved in code."
        )


def build_consumer_contract_snapshot(
    acceptance: ConsumerContractAcceptance,
    *,
    expected_catalog_version: str,
    accepted_at: int,
) -> dict[str, Any]:
    """Validate browser evidence and return the immutable server-owned snapshot."""
    if acceptance.catalog_version != expected_catalog_version:
        raise ConsumerContractValidationError("Credit catalog version is stale")
    if isinstance(accepted_at, bool) or accepted_at <= 0:
        raise ConsumerContractValidationError("Acceptance timestamp is invalid")

    canonical = public_consumer_contract(acceptance.locale)
    expected_identity = {
        "disclosure_id": canonical["disclosure_id"],
        "disclosure_sha256": canonical["disclosure_sha256"],
        "policy_version": canonical["policy_version"],
        "terms_version": canonical["terms_version"],
        "withdrawal_notice_version": canonical["withdrawal_notice_version"],
    }
    supplied_identity = {
        "disclosure_id": acceptance.disclosure_id,
        "disclosure_sha256": acceptance.disclosure_sha256,
        "policy_version": acceptance.policy_version,
        "terms_version": acceptance.terms_version,
        "withdrawal_notice_version": acceptance.withdrawal_notice_version,
    }
    if supplied_identity != expected_identity:
        raise ConsumerContractValidationError("Consumer-contract disclosure is stale")

    consent_values = (
        acceptance.terms_accepted,
        acceptance.immediate_performance_requested,
        acceptance.withdrawal_consequences_acknowledged,
    )
    if any(type(value) is not bool or value is not True for value in consent_values):
        raise ConsumerContractValidationError("All consumer-contract acceptances are required")

    acceptance_text = canonical["required_acceptances"]
    return {
        **canonical,
        "catalog_version": expected_catalog_version,
        "accepted_at": accepted_at,
        "acceptances": {
            "terms": {
                "accepted": True,
                "accepted_at": accepted_at,
                "text": acceptance_text["terms"],
                "text_sha256": _sha256_text(acceptance_text["terms"]),
            },
            "immediate_performance": {
                "accepted": True,
                "accepted_at": accepted_at,
                "text": acceptance_text["immediate_performance"],
                "text_sha256": _sha256_text(acceptance_text["immediate_performance"]),
            },
            "withdrawal_consequences": {
                "accepted": True,
                "accepted_at": accepted_at,
                "text": acceptance_text["withdrawal_consequences"],
                "text_sha256": _sha256_text(acceptance_text["withdrawal_consequences"]),
            },
        },
    }


def consumer_contract_snapshot_sha256(snapshot: dict[str, Any]) -> str:
    """Return the digest bound into Stripe metadata and durable confirmation."""
    return hashlib.sha256(_canonical_json(snapshot)).hexdigest()
