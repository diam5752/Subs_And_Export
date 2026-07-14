#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import subprocess
import tempfile
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests

BASE = "https://diavgeia.gov.gr"
SEARCH_URL = BASE + "/luminapi/opendata/search"
DETAIL_URL = BASE + "/luminapi/api/decisions/{ada}"
DOC_URL = BASE + "/doc/{ada}"
OUT = Path("enriched-hunter-output")
DATE_FROM = "2023-01-01"
DATE_TO = "2026-07-14"
PAGE_SIZE = 100
MAX_PDF_RECORDS = 180
REQUEST_SLEEP = 0.22

# These are discovery lenses, never evidence by themselves.
LENSES: tuple[tuple[str, str, int], ...] = (
    ("without_publication", "χωρίς προηγούμενη δημοσίευση", 4),
    ("single_bid", "μοναδική προσφορά", 4),
    ("single_bid", "μία προσφορά", 3),
    ("emergency", "κατεπείγουσα ανάγκη", 3),
    ("direct_award", "απευθείας ανάθεση", 3),
    ("modification", "2η τροποποίηση σύμβασης", 4),
    ("modification", "3η τροποποίηση σύμβασης", 4),
    ("modification", "συμπληρωματική σύμβαση", 4),
    ("modification", "3ος ΑΠΕ", 4),
    ("modification", "3ου ΑΠΕ", 4),
    ("unit_price", "γραβάτες", 3),
    ("unit_price", "γραβάτα", 3),
    ("unit_price", "φουλάρια", 3),
    ("unit_price", "φουλάρι", 3),
    ("unit_price", "κλιματιστικά", 4),
    ("unit_price", "κλιματιστικό", 4),
    ("unit_price", "air condition", 3),
    ("unit_price", "φορητοί υπολογιστές", 3),
    ("unit_price", "laptop", 3),
    ("unit_price", "τιμή μονάδας", 3),
    ("unusual_spend", "αναμνηστικά δώρα", 3),
    ("unusual_spend", "διαφημιστικά δώρα", 3),
)

ADAM_RE = re.compile(r"\b\d{2}(?:REQ|PROC|AWRD|SYMV|PAY)\d{9}\*?\b", re.I)
ADA_RE = re.compile(r"\b[0-9Α-Ω]{4,12}-[0-9Α-Ω]{3}\b", re.I)
AFM_CONTEXT_RE = re.compile(r"(?:Α\.?Φ\.?Μ\.?|AFM)\s*[:#]?\s*(\d{9})", re.I)
AMOUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)",
    re.I,
)
DATE_RANGE_RE = re.compile(
    r"(?:από\s*)?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*(?:έως|ως|μέχρι|-)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    re.I,
)
MONTH_DURATION_RE = re.compile(r"(?:διάστημα|διάρκεια)[^\n.]{0,80}?(\d{1,2})\s*\(?\s*μην", re.I)
QUANTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ποσ(?:ότητα|ότης)\s*[:=]?\s*(\d{1,5})", re.I),
    re.compile(r"(\d{1,5})\s*(?:τεμάχια|τεμ\.?|μονάδες|τεμ\s|pcs\b)", re.I),
    re.compile(r"(\d{1,5})\s*(?:γραβάτες|γραβατών|φουλάρια|φουλαριών|κλιματιστικά|κλιματιστικών|φορητοί υπολογιστές|φορητών υπολογιστών|laptops?)", re.I),
)
UNIT_PRICE_RE = re.compile(
    r"(?:τιμή\s*μονάδ(?:ας|ος)|ανά\s*τεμάχιο|/\s*τεμ\.?)\s*[:=]?\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ)?",
    re.I,
)
BTU_RE = re.compile(r"(\d{1,2}(?:[.]\d{3})?|\d{4,5})\s*BTU", re.I)

PROCEDURE_PHRASES = (
    "χωρίς προηγούμενη δημοσίευση",
    "απευθείας ανάθεση",
    "μοναδική προσφορά",
    "μία προσφορά",
    "ένας προσφέρων",
    "κατεπείγουσα ανάγκη",
    "λόγω κατεπείγοντος",
)
MODIFICATION_PHRASES = (
    "τροποποίηση σύμβασης",
    "2η τροποποίηση",
    "δεύτερη τροποποίηση",
    "3η τροποποίηση",
    "τρίτη τροποποίηση",
    "συμπληρωματική σύμβαση",
    "ανακεφαλαιωτικός πίνακας",
    "3ος απε",
    "3ου απε",
    "παράταση σύμβασης",
)
ORDINARY_EXPLANATION_PHRASES = (
    "ανοικτός ηλεκτρονικός διαγωνισμός",
    "διεθνής ηλεκτρονικός διαγωνισμός",
    "βρίσκεται στο στάδιο της αξιολόγησης",
    "αναμένεται να ολοκληρωθεί",
    "μέχρι την ολοκλήρωση",
    "δημόσιας υγείας",
    "αποκλειστικό δικαίωμα",
    "αποκλειστικός διανομέας",
    "μοναδικός εξουσιοδοτημένος",
    "απουσία ανταγωνισμού για τεχνικούς λόγους",
    "άγονος διαγωνισμός",
    "δεν υποβλήθηκε προσφορά",
)

BOILERPLATE_TOKENS = {
    "αποφαση", "εγκριση", "επικυρωση", "πρακτικου", "πρακτικο", "επιτροπης",
    "διαδικασια", "διαπραγματευση", "χωρις", "προηγουμενη", "δημοσιευση",
    "απευθειας", "αναθεση", "συμβαση", "συμβασης", "προμηθεια", "υπηρεσιων",
    "υπηρεσια", "δαπανη", "δαπανης", "παροχη", "προηγουμενης", "συμφωνα",
    "διαταξεις", "αρθρου", "του", "της", "των", "για", "και", "στο", "στη",
    "στην", "με", "απο", "εως", "ενα", "δυο", "τρεις", "μηνες", "μηνα",
    "ετος", "ετη", "γενικου", "νοσοκομειου", "δημου", "φορεα", "θεμα",
}

OBJECT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cleaning", ("καθαρισμ", "καθαριοτητα")),
    ("food_service", ("διανομ", "παρασκευ", "φαγητ", "εστιασ")),
    ("medical_waste", ("νοσοκομειακ", "αποβλητ", "εααμ", "μεα")),
    ("medical_device_maintenance", ("ιατροτεχνολογ", "αξονικ", "τομογραφ", "γαστροσκοπ", "κολονοσκοπ", "γραμμικ", "επιταχυντ", "monitor", "draeger", "pentax", "philips", "ge healthcare")),
    ("software_maintenance", ("λογισμικ", "πληροφοριακ", "εφαρμογ", "software", "τεχνικη υποστηριξη")),
    ("water_facility_operations", ("εεν αποσελεμη", "εγκατασταση επεξεργασιας νερου", "εργων αποσελεμη")),
    ("air_conditioner", ("κλιματιστικ", "air condition", "btu")),
    ("necktie_scarf", ("γραβατ", "φουλαρ")),
    ("laptop", ("φορητ", "υπολογιστ", "laptop")),
    ("printer", ("εκτυπωτ", "printer")),
    ("chair_furniture", ("καρεκλ", "καθισμα", "επιπλ")),
    ("gifts_promotional", ("αναμνηστικ", "δωρ", "διαφημιστικ", "προωθητικ")),
    ("construction", ("εργο", "κατασκευ", "ανακατασκευ", "διαμορφωσ", "οδοποι")),
)


@dataclass
class RawSeed:
    ada: str
    lens: str
    term: str
    record: dict[str, Any]
    seed_score: int


@dataclass
class Decision:
    ada: str
    official_url: str
    organization_id: str
    organization: str
    subject: str
    issue_date: str | None
    publish_date: str | None
    decision_type: str
    status: str
    corrected: bool
    private: bool
    amount: float | None
    amount_basis: str
    supplier_name: str
    supplier_key: str
    cpv: str
    object_category: str
    object_signature: str
    adams: set[str] = field(default_factory=set)
    related_adas: set[str] = field(default_factory=set)
    procedure_flags: set[str] = field(default_factory=set)
    modification_flags: set[str] = field(default_factory=set)
    ordinary_explanations: list[str] = field(default_factory=list)
    duration_months: int | None = None
    quantity: int | None = None
    unit_price: float | None = None
    unit_price_source: str = ""
    product_spec: str = ""
    lens_hits: set[str] = field(default_factory=set)
    evidence: list[str] = field(default_factory=list)

    def current(self) -> bool:
        return self.status == "PUBLISHED" and not self.corrected and not self.private


class DSU:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def compact(value: str, limit: int = 800) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_money(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("€", "").replace("EUR", "").replace("eur", "")
    text = text.replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        if text.count(".") > 1:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def ms_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def request(session: requests.Session, url: str, *, params: dict[str, Any] | None = None, timeout: int = 45) -> requests.Response:
    last: Exception | None = None
    for attempt in range(5):
        try:
            response = session.get(url, params=params, timeout=timeout, allow_redirects=True)
            if response.status_code in {429, 502, 503, 504}:
                time.sleep(2 ** attempt)
                continue
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {last}")


def extract_pdf_text(content: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="diavgeia-enriched-") as tmp:
        pdf = Path(tmp) / "doc.pdf"
        txt = Path(tmp) / "doc.txt"
        pdf.write_bytes(content)
        completed = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(txt)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not txt.exists():
            return ""
        return txt.read_text(encoding="utf-8", errors="replace")[:220_000]


def search_lens(session: requests.Session, lens: str, term: str, pages: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for page in range(pages):
        response = request(
            session,
            SEARCH_URL,
            params={
                "page": page,
                "size": PAGE_SIZE,
                "term": term,
                "from_issue_date": DATE_FROM,
                "to_issue_date": DATE_TO,
            },
        )
        if not response.ok:
            attempts.append({"lens": lens, "term": term, "page": page, "status": response.status_code, "returned": 0})
            break
        payload = response.json()
        decisions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(decisions, list):
            attempts.append({"lens": lens, "term": term, "page": page, "status": "invalid_json", "returned": 0})
            break
        attempts.append({"lens": lens, "term": term, "page": page, "status": 200, "returned": len(decisions)})
        records.extend(item for item in decisions if isinstance(item, dict))
        if len(decisions) < PAGE_SIZE:
            break
        time.sleep(REQUEST_SLEEP)
    return records, attempts


def extra_fields(detail: dict[str, Any]) -> dict[str, Any]:
    value = detail.get("extraFieldValues")
    return value if isinstance(value, dict) else {}


def amount_from_detail(detail: dict[str, Any], text: str) -> tuple[float | None, str]:
    extra = extra_fields(detail)
    for key, basis in (("awardAmount", "unknown"), ("amount", "unknown"), ("budget", "unknown")):
        value = extra.get(key)
        if isinstance(value, dict):
            parsed = parse_money(value.get("amount"))
            if parsed is not None:
                return parsed, basis
        parsed = parse_money(value)
        if parsed is not None:
            return parsed, basis
    matches = [parse_money(match.group(1)) for match in AMOUNT_RE.finditer(text)]
    usable = [value for value in matches if value is not None and value >= 1]
    if not usable:
        return None, "unknown"
    # Metadata is preferable. PDF fallback keeps only a plausible headline value and
    # is never treated as a payment or legal amount contradiction.
    return max(usable), "pdf_max_unknown"


def supplier_from_detail(detail: dict[str, Any], text: str) -> tuple[str, str]:
    extra = extra_fields(detail)
    persons = extra.get("person")
    if isinstance(persons, list):
        for item in persons:
            if not isinstance(item, dict):
                continue
            name = compact(item.get("name"), 220)
            afm = re.sub(r"\D", "", str(item.get("afm") or ""))
            if len(afm) == 9:
                return name, hashlib.sha256(afm.encode()).hexdigest()[:16]
            if name:
                return name, "name:" + fold(name)[:80]
    afm_match = AFM_CONTEXT_RE.search(text)
    if afm_match:
        afm = afm_match.group(1)
        left = max(0, afm_match.start() - 240)
        context = compact(text[left:afm_match.start()], 240)
        name_match = re.search(r"(?:εταιρε(?:ία|ιας)|αναδόχ(?:ου|ος)|προμηθευτ(?:ή|ης))\s*[:\-]?\s*[«\"]?([^\n;,.]{3,140})", context, re.I)
        name = compact(name_match.group(1), 180) if name_match else ""
        return name, hashlib.sha256(afm.encode()).hexdigest()[:16]
    return "", ""


def object_category(text: str) -> str:
    value = fold(text)
    for category, terms in OBJECT_RULES:
        if any(term in value for term in terms):
            return category
    return "other"


def object_signature(text: str, category: str) -> str:
    tokens = []
    for token in re.findall(r"[a-zα-ω0-9]+", fold(text)):
        if len(token) < 4 or token.isdigit() or token in BOILERPLATE_TOKENS:
            continue
        if token not in tokens:
            tokens.append(token)
    specific = ":".join(tokens[:8])
    return f"{category}:{specific}" if specific else category


def detect_flags(text: str) -> tuple[set[str], set[str], list[str]]:
    value = fold(text)
    procedure: set[str] = set()
    if "χωρις προηγουμενη δημοσιευση" in value:
        procedure.add("without_publication")
    if "απευθειας αναθεση" in value:
        procedure.add("direct_award")
    if any(phrase in value for phrase in ("μοναδικη προσφορα", "μια προσφορα", "ενας προσφερων")):
        procedure.add("single_bid")
    if any(phrase in value for phrase in ("κατεπειγουσα αναγκη", "λογω κατεπειγοντος", "εκτακτη αναγκη")):
        procedure.add("emergency")

    modification: set[str] = set()
    for phrase in MODIFICATION_PHRASES:
        normalized = fold(phrase)
        if normalized in value:
            modification.add(normalized.replace(" ", "_"))

    explanations = [phrase for phrase in ORDINARY_EXPLANATION_PHRASES if fold(phrase) in value]
    return procedure, modification, explanations


def duration_months(text: str) -> int | None:
    match = MONTH_DURATION_RE.search(text)
    if match:
        try:
            value = int(match.group(1))
            if 1 <= value <= 60:
                return value
        except ValueError:
            pass
    return None


def quantity_and_unit_price(text: str, amount: float | None, category: str) -> tuple[int | None, float | None, str, str]:
    quantities: list[int] = []
    for pattern in QUANTITY_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            if 1 <= value <= 100_000:
                quantities.append(value)
    explicit_prices = [parse_money(match.group(1)) for match in UNIT_PRICE_RE.finditer(text)]
    explicit_prices = [value for value in explicit_prices if value is not None and 0 < value < 1_000_000]
    quantity = statistics.mode(quantities) if quantities else None
    if explicit_prices:
        unit_price = statistics.median(explicit_prices)
        source = "explicit_unit_price"
    elif quantity and amount and amount > 0:
        unit_price = amount / quantity
        source = "headline_amount_divided_by_quantity"
    else:
        unit_price = None
        source = ""
    spec = ""
    if category == "air_conditioner":
        values = []
        for match in BTU_RE.finditer(text):
            raw = match.group(1).replace(".", "")
            try:
                btu = int(raw)
            except ValueError:
                continue
            if 5_000 <= btu <= 100_000:
                values.append(btu)
        if values:
            spec = f"{statistics.mode(values)}BTU"
    return quantity, unit_price, source, spec


def seed_score(record: dict[str, Any], lens: str) -> int:
    text = fold(str(record.get("subject") or ""))
    score = 0
    if lens == "without_publication":
        score += 28
    elif lens == "single_bid":
        score += 32
    elif lens == "modification":
        score += 24
    elif lens == "emergency":
        score += 14
    elif lens == "direct_award":
        score += 10
    elif lens == "unit_price":
        score += 18
    elif lens == "unusual_spend":
        score += 15
    if any(term in text for term in ("2η τροποποιηση", "3η τροποποιηση", "3ος απε", "3ου απε")):
        score += 16
    if any(term in text for term in ("ενα μηνα", "δυο μηνες", "τρεις μηνες", "τεσσερις μηνες")):
        score += 8
    extra = record.get("extraFieldValues") if isinstance(record.get("extraFieldValues"), dict) else {}
    amount_value = extra.get("awardAmount")
    if isinstance(amount_value, dict):
        amount_value = amount_value.get("amount")
    amount = parse_money(amount_value)
    if amount is not None:
        if amount >= 500_000:
            score += 10
        elif amount >= 100_000:
            score += 7
        elif amount >= 30_000:
            score += 3
    return score


def inspect_decision(session: requests.Session, seed: RawSeed, lens_hits: set[str]) -> Decision | None:
    ada = seed.ada
    encoded = quote(ada, safe="")
    detail_response = request(session, DETAIL_URL.format(ada=encoded))
    if not detail_response.ok:
        return None
    detail = detail_response.json()
    if not isinstance(detail, dict):
        return None
    status = str(detail.get("status") or "")
    corrected = bool(detail.get("correctedVersionId"))
    private = bool(detail.get("privateData"))
    document_url = str(detail.get("documentUrl") or DOC_URL.format(ada=encoded))
    pdf_response = request(session, document_url, timeout=60)
    pdf_text = ""
    if pdf_response.ok and "pdf" in pdf_response.headers.get("content-type", "").casefold():
        pdf_text = extract_pdf_text(pdf_response.content)
    extra = extra_fields(detail)
    subject = compact(detail.get("subject"), 1000)
    joined = "\n".join([subject, json.dumps(extra, ensure_ascii=False, default=str), pdf_text])
    amount, amount_basis = amount_from_detail(detail, joined)
    supplier_name, supplier_key = supplier_from_detail(detail, joined)
    cpv_raw = extra.get("cpv")
    if isinstance(cpv_raw, list):
        cpv = ",".join(compact(item, 40) for item in cpv_raw)
    else:
        cpv = compact(cpv_raw, 100)
    category = object_category(joined)
    signature = object_signature(subject + " " + pdf_text[:12_000], category)
    procedure, modifications, explanations = detect_flags(joined)
    qty, unit_price, unit_price_source, spec = quantity_and_unit_price(joined, amount, category)
    adams = {match.group(0).upper() for match in ADAM_RE.finditer(joined)}
    related_adas = {match.group(0).upper() for match in ADA_RE.finditer(json.dumps(extra, ensure_ascii=False, default=str))}
    evidence = []
    if procedure:
        evidence.append("Διαδικασία: " + ", ".join(sorted(procedure)))
    if modifications:
        evidence.append("Μεταβολές: " + ", ".join(sorted(modifications)))
    if amount is not None:
        evidence.append(f"Δηλωμένο/εξαγόμενο ποσό: €{amount:,.2f} ({amount_basis})")
    if supplier_name or supplier_key:
        evidence.append("Ανάδοχος/προμηθευτής αναγνωρίστηκε στα επίσημα στοιχεία.")
    if qty and unit_price:
        evidence.append(f"Ποσότητα {qty}, τιμή μονάδας περίπου €{unit_price:,.2f} ({unit_price_source}).")
    return Decision(
        ada=ada,
        official_url=document_url,
        organization_id=str(detail.get("organizationId") or ""),
        organization=compact(detail.get("organizationLabel") or detail.get("organization") or "", 300),
        subject=subject,
        issue_date=ms_iso(detail.get("issueDate")),
        publish_date=ms_iso(detail.get("publishTimestamp")),
        decision_type=str(detail.get("decisionTypeId") or ""),
        status=status,
        corrected=corrected,
        private=private,
        amount=amount,
        amount_basis=amount_basis,
        supplier_name=supplier_name,
        supplier_key=supplier_key,
        cpv=cpv,
        object_category=category,
        object_signature=signature,
        adams=adams,
        related_adas=related_adas,
        procedure_flags=procedure,
        modification_flags=modifications,
        ordinary_explanations=explanations,
        duration_months=duration_months(joined),
        quantity=qty,
        unit_price=unit_price,
        unit_price_source=unit_price_source,
        product_spec=spec,
        lens_hits=set(lens_hits),
        evidence=evidence,
    )


def collapse_chains(decisions: list[Decision]) -> dict[str, list[Decision]]:
    dsu = DSU(decision.ada for decision in decisions)
    by_identifier: dict[str, list[str]] = defaultdict(list)
    for decision in decisions:
        for identifier in decision.adams:
            by_identifier["adam:" + identifier].append(decision.ada)
        for identifier in decision.related_adas:
            if identifier in dsu.parent:
                by_identifier["ada:" + identifier].append(decision.ada)
        if decision.amount is not None and decision.issue_date:
            exact = f"exact:{decision.organization_id}:{decision.issue_date}:{round(decision.amount, 2)}:{decision.object_signature}"
            by_identifier[exact].append(decision.ada)
    for values in by_identifier.values():
        for other in values[1:]:
            dsu.union(values[0], other)
    output: dict[str, list[Decision]] = defaultdict(list)
    for decision in decisions:
        output[dsu.find(decision.ada)].append(decision)
    return dict(output)


def chain_representatives(chains: dict[str, list[Decision]]) -> list[Decision]:
    representatives = []
    for items in chains.values():
        items = sorted(
            items,
            key=lambda item: (
                bool(item.supplier_key),
                bool(item.amount),
                len(item.procedure_flags) + len(item.modification_flags),
                item.publish_date or "",
            ),
            reverse=True,
        )
        representatives.append(items[0])
    return representatives


def serialize_decision(decision: Decision) -> dict[str, Any]:
    return {
        "ada": decision.ada,
        "official_url": decision.official_url,
        "organization_id": decision.organization_id,
        "organization": decision.organization,
        "subject": decision.subject,
        "issue_date": decision.issue_date,
        "publish_date": decision.publish_date,
        "amount_eur": round(decision.amount, 2) if decision.amount is not None else None,
        "amount_basis": decision.amount_basis,
        "supplier_name": decision.supplier_name,
        "supplier_key_hash": decision.supplier_key,
        "cpv": decision.cpv,
        "object_category": decision.object_category,
        "object_signature": decision.object_signature,
        "adams": sorted(decision.adams),
        "procedure_flags": sorted(decision.procedure_flags),
        "modification_flags": sorted(decision.modification_flags),
        "ordinary_explanations": decision.ordinary_explanations,
        "duration_months": decision.duration_months,
        "quantity": decision.quantity,
        "unit_price_eur": round(decision.unit_price, 2) if decision.unit_price is not None else None,
        "unit_price_source": decision.unit_price_source,
        "product_spec": decision.product_spec,
        "evidence": decision.evidence,
    }


def repeated_pattern_candidates(representatives: list[Decision]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Decision]] = defaultdict(list)
    for decision in representatives:
        groups[(decision.organization_id, decision.object_category)].append(decision)
    candidates = []
    for (organization_id, category), items in groups.items():
        active = [item for item in items if item.current()]
        if len(active) < 2:
            continue
        noncompetitive = [item for item in active if item.procedure_flags]
        if len(noncompetitive) < 2:
            continue
        supplier_keys = [item.supplier_key for item in noncompetitive if item.supplier_key]
        same_supplier = bool(supplier_keys) and max(supplier_keys.count(key) for key in set(supplier_keys)) >= 2
        short = [item for item in noncompetitive if item.duration_months is not None and item.duration_months <= 6]
        explicit_bridge = any(item.ordinary_explanations for item in noncompetitive)
        total = sum(item.amount or 0 for item in noncompetitive)
        families = ["repeated_noncompetitive_procedure"]
        if same_supplier:
            families.append("supplier_concentration")
        if len(short) >= 2 and explicit_bridge:
            families.append("repeated_short_bridge")
        score = 52 + min(18, 7 * (len(noncompetitive) - 1))
        if same_supplier:
            score += 12
        if len(short) >= 2 and explicit_bridge:
            score += 10
        if total >= 500_000:
            score += 6
        elif total >= 100_000:
            score += 3
        if len(families) < 2:
            score = min(score, 69)
        score = min(94, score)
        selected = sorted(noncompetitive, key=lambda item: item.issue_date or "", reverse=True)[:8]
        candidates.append({
            "type": "repeated_noncompetitive_chain",
            "review_priority": score,
            "organization_id": organization_id,
            "object_category": category,
            "independent_families": families,
            "distinct_chain_count": len(noncompetitive),
            "same_supplier_repeated": same_supplier,
            "explicit_ordinary_explanation_found": explicit_bridge,
            "known_cumulative_value_eur": round(total, 2),
            "strongest_ordinary_explanation": "Continuity of essential services, technical exclusivity, or a pending open tender may justify temporary exceptional procedures; the repeated pattern still warrants checking why the ordinary process did not conclude earlier.",
            "documents": [serialize_decision(item) for item in selected],
        })
    return candidates


def modification_candidates(representatives: list[Decision]) -> list[dict[str, Any]]:
    candidates = []
    for decision in representatives:
        flags = decision.modification_flags
        if not flags:
            continue
        advanced = any(flag.startswith(("2η_", "δευτερη_", "3η_", "τριτη_", "3ος_", "3ου_")) for flag in flags)
        amount_mentions = decision.amount or 0
        score = 46 + (18 if advanced else 7)
        families = ["contract_modification"]
        if len(decision.adams) >= 2:
            families.append("linked_contract_chain")
            score += 9
        if amount_mentions >= 100_000:
            score += 5
        if len(families) < 2:
            score = min(score, 69)
        candidates.append({
            "type": "cumulative_or_advanced_modification",
            "review_priority": min(86, score),
            "organization_id": decision.organization_id,
            "object_category": decision.object_category,
            "independent_families": families,
            "distinct_chain_count": 1,
            "known_cumulative_value_eur": round(decision.amount or 0, 2),
            "strongest_ordinary_explanation": "A later APE or modification may only redistribute quantities or implement a legally permitted minor change. The original and every intermediate value must be reconstructed before calling it a financial increase.",
            "documents": [serialize_decision(decision)],
        })
    return candidates


def unit_price_candidates(representatives: list[Decision]) -> list[dict[str, Any]]:
    by_product: dict[tuple[str, str], list[Decision]] = defaultdict(list)
    for decision in representatives:
        if decision.unit_price is None or decision.quantity is None:
            continue
        if decision.amount_basis == "pdf_max_unknown" and decision.unit_price_source != "explicit_unit_price":
            continue
        spec = decision.product_spec or "unspecified"
        by_product[(decision.object_category, spec)].append(decision)
    candidates = []
    for (category, spec), items in by_product.items():
        if len(items) < 4:
            continue
        prices = [item.unit_price for item in items if item.unit_price is not None]
        if len(prices) < 4:
            continue
        median = statistics.median(prices)
        if median <= 0:
            continue
        for item in items:
            assert item.unit_price is not None
            ratio = item.unit_price / median
            difference = item.unit_price - median
            if ratio < 2.5 or difference < max(50, median * 0.5):
                continue
            candidates.append({
                "type": "comparable_unit_price_outlier",
                "review_priority": min(92, 62 + int(min(24, (ratio - 2.5) * 8))),
                "organization_id": item.organization_id,
                "object_category": category,
                "product_spec": spec,
                "independent_families": ["comparable_unit_price"],
                "peer_count": len(items),
                "unit_price_eur": round(item.unit_price, 2),
                "peer_median_unit_price_eur": round(median, 2),
                "ratio_to_peer_median": round(ratio, 2),
                "strongest_ordinary_explanation": "The total may include installation, removal, warranty, accessories, delivery, or a different technical specification. The case is only a price lead until scope and VAT basis are shown to be comparable.",
                "documents": [serialize_decision(item)],
                "peer_examples": [serialize_decision(peer) for peer in sorted(items, key=lambda value: value.unit_price or 0)[:5]],
            })
    return candidates


def publication_lag_metrics(representatives: list[Decision]) -> dict[str, Any]:
    lags = []
    for item in representatives:
        if not item.issue_date or not item.publish_date:
            continue
        try:
            issue = datetime.fromisoformat(item.issue_date)
            publish = datetime.fromisoformat(item.publish_date)
        except ValueError:
            continue
        days = (publish - issue).days
        if days >= 0:
            lags.append(days)
    return {
        "count": len(lags),
        "median_days": statistics.median(lags) if lags else None,
        "over_30_days": sum(value > 30 for value in lags),
        "note": "Publication lag is measurable as a transparency/administrative signal only; it is not treated as proof of procurement misconduct.",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "MizAI enriched temporary Diavgeia hunter/1.0",
        "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.1",
    })

    by_ada: dict[str, RawSeed] = {}
    lens_hits: dict[str, set[str]] = defaultdict(set)
    attempts: list[dict[str, Any]] = []
    for lens, term, pages in LENSES:
        records, current_attempts = search_lens(session, lens, term, pages)
        attempts.extend(current_attempts)
        for record in records:
            ada = str(record.get("ada") or "").strip()
            if not ada:
                continue
            lens_hits[ada].add(lens)
            candidate = RawSeed(ada=ada, lens=lens, term=term, record=record, seed_score=seed_score(record, lens))
            previous = by_ada.get(ada)
            if previous is None or candidate.seed_score > previous.seed_score:
                by_ada[ada] = candidate
        time.sleep(REQUEST_SLEEP)

    ranked = sorted(
        by_ada.values(),
        key=lambda item: (item.seed_score, len(lens_hits[item.ada])),
        reverse=True,
    )
    # Preserve explicit product/unit-price coverage while keeping the run bounded.
    unit_seeds = [item for item in ranked if "unit_price" in lens_hits[item.ada] or "unusual_spend" in lens_hits[item.ada]]
    general_seeds = [item for item in ranked if item not in unit_seeds]
    selected_by_ada: dict[str, RawSeed] = {}
    for item in unit_seeds[:80] + general_seeds[:MAX_PDF_RECORDS]:
        selected_by_ada.setdefault(item.ada, item)
        if len(selected_by_ada) >= MAX_PDF_RECORDS:
            break

    decisions: list[Decision] = []
    failures: list[dict[str, str]] = []
    for index, seed in enumerate(selected_by_ada.values(), start=1):
        try:
            decision = inspect_decision(session, seed, lens_hits[seed.ada])
            if decision is not None:
                decisions.append(decision)
        except Exception as exc:
            failures.append({"ada": seed.ada, "error": type(exc).__name__, "message": str(exc)[:300]})
        if index % 10 == 0:
            print(f"inspected {index}/{len(selected_by_ada)}", flush=True)
        time.sleep(REQUEST_SLEEP)

    current = [item for item in decisions if item.current()]
    chains = collapse_chains(current)
    representatives = chain_representatives(chains)

    candidates = [
        *repeated_pattern_candidates(representatives),
        *modification_candidates(representatives),
        *unit_price_candidates(representatives),
    ]
    candidates.sort(key=lambda item: (item.get("review_priority", 0), item.get("known_cumulative_value_eur", 0)), reverse=True)

    # Do not allow a price lead with one evidence family to masquerade as a validated 80+ case.
    for item in candidates:
        if len(item.get("independent_families") or []) < 2:
            item["review_priority"] = min(int(item.get("review_priority") or 0), 69)
            item["delivery_status"] = "BEST_RESEARCH_LEAD"
        elif int(item.get("review_priority") or 0) >= 80:
            item["delivery_status"] = "FOUND_VALIDATED"
        else:
            item["delivery_status"] = "BEST_RESEARCH_LEAD"

    measurable = {
        "repeated_noncompetitive_chains": {
            "status": "measurable",
            "requirements": "same authority + same object/CPV + distinct collapsed chains; same supplier strengthens the finding",
        },
        "repeated_short_bridge_contracts": {
            "status": "measurable_when_dates_and_duration_exist",
            "requirements": "two or more distinct short chains plus explicit pending/open-tender context",
        },
        "supplier_concentration_within_authority_object": {
            "status": "measurable_when_supplier_identity_is_available",
            "requirements": "stable supplier AFM/name across distinct chains",
        },
        "advanced_or_repeated_modifications": {
            "status": "partly_measurable",
            "requirements": "modification number and official chain are measurable; financial increase requires reliable original/intermediate/final amounts",
        },
        "unit_price_outliers": {
            "status": "measurable_only_with_quantity_unit_scope_and_peers",
            "requirements": "explicit quantity or unit price, compatible VAT/scope, and at least four genuinely comparable official records",
        },
        "publication_lag": {
            "status": "measurable_as_transparency_signal_only",
            "requirements": "typed issue and publication dates; not evidence of illegality",
        },
        "payment_vs_contract_mismatch": {
            "status": "not_reliably_measured_in_this_run",
            "requirements": "linked contract/payment identities, installment-vs-cumulative semantics, and compatible VAT basis",
        },
        "bid_rigging_or_cartel": {
            "status": "not_measurable_from_standard_Diavgeia_metadata_alone",
            "requirements": "bid-level participants, prices, withdrawals, submission metadata, or another authoritative source",
        },
        "conflict_of_interest_or_hidden_ownership": {
            "status": "not_measurable_from_Diavgeia_alone",
            "requirements": "authoritative company/ownership and public-official relationship data",
        },
        "market_overpricing_without_quantity": {
            "status": "not_measurable",
            "requirements": "a large total or an unusual item title alone is insufficient",
        },
    }

    coverage = {
        "status": "completed" if decisions else "source_failure",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "search_attempts": attempts,
        "unique_metadata_records": len(by_ada),
        "selected_for_pdf_inspection": len(selected_by_ada),
        "successful_inspections": len(decisions),
        "current_official_decisions": len(current),
        "collapsed_chain_count": len(chains),
        "candidate_count": len(candidates),
        "validated_80_plus_count": sum(item.get("delivery_status") == "FOUND_VALIDATED" for item in candidates),
        "failures": failures,
        "publication_lag": publication_lag_metrics(representatives),
        "notes": [
            "Discovery terms are not treated as evidence.",
            "Records sharing ADA/ADAM identifiers or exact administrative duplicates are collapsed before scoring.",
            "A unit-price candidate cannot pass 80 without a second independent family.",
            "The run is bounded and not an exhaustive census of Diavgeia.",
        ],
    }

    result = {
        "coverage": coverage,
        "measurable_signal_matrix": measurable,
        "top_candidates": candidates[:25],
    }
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "measurable-signals.json").write_text(json.dumps(measurable, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "rank\tstatus\tscore\ttype\torganization_id\tobject_category\tchain_count\tknown_value\tadas",
    ]
    for index, item in enumerate(candidates[:25], start=1):
        adas = ",".join(doc.get("ada", "") for doc in item.get("documents", []))
        lines.append("\t".join([
            str(index),
            str(item.get("delivery_status") or ""),
            str(item.get("review_priority") or 0),
            str(item.get("type") or ""),
            str(item.get("organization_id") or ""),
            str(item.get("object_category") or ""),
            str(item.get("distinct_chain_count") or 0),
            str(item.get("known_cumulative_value_eur") or ""),
            adas,
        ]))
    (OUT / "top-candidates.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "unique_metadata_records": coverage["unique_metadata_records"],
        "successful_inspections": coverage["successful_inspections"],
        "collapsed_chain_count": coverage["collapsed_chain_count"],
        "candidate_count": coverage["candidate_count"],
        "validated_80_plus_count": coverage["validated_80_plus_count"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
