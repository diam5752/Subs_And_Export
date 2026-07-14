#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
import subprocess
import tempfile
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

BASE = "https://diavgeia.gov.gr"
SEARCH = BASE + "/luminapi/opendata/search"
DETAIL = BASE + "/luminapi/api/decisions/{ada}"
DOC = BASE + "/doc/{ada}"
OUT = Path("manual-diverse-output")
TODAY = date(2026, 7, 14)
SEED = 5600714
PAGE_SIZE = 100
MAX_DEEP = 260
SLEEP = 0.16

# Discovery terms are only entry points. They never become evidence by themselves.
LANES: dict[str, tuple[str, ...]] = {
    "competition": ("μοναδική προσφορά", "μία προσφορά", "ένας προσφέρων"),
    "direct_award": ("απευθείας ανάθεση",),
    "emergency": ("κατεπείγουσα ανάγκη", "έκτακτη ανάγκη"),
    "timeline": ("τακτοποίηση οφειλής", "παρασχεθείσες υπηρεσίες", "αναδρομική ισχύ"),
    "unit_price": (
        "τιμή μονάδας", "γραβάτες", "φουλάρια", "κλιματιστικά", "air condition",
        "φορητοί υπολογιστές", "laptop", "φαναράκια", "καρέκλες", "εκτυπωτές",
        "οθόνες υπολογιστών", "χημικά αντιδραστήρια",
    ),
    "modification": ("3η τροποποίηση σύμβασης", "3ος ΑΠΕ"),
}
YEAR_WINDOWS = (("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-07-14"))

ADAM_RE = re.compile(r"\b\d{2}(?:REQ|PROC|AWRD|SYMV|PAY)\d{9}\*?\b", re.I)
ADA_RE = re.compile(r"\b[0-9Α-Ω]{4,12}-[0-9Α-Ω]{3}\b", re.I)
AFM_RE = re.compile(r"(?:Α\.?Φ\.?Μ\.?|AFM)\s*[:#]?\s*(\d{9})", re.I)
MONEY_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)", re.I)
UNIT_PRICE_RE = re.compile(r"(?:τιμή\s*μονάδ(?:ας|ος)|ανά\s*τεμάχιο|/\s*τεμ\.?|τιμή\s*ανά\s*μονάδα)\s*[:=]?\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ)?", re.I)
QTY_PATTERNS = (
    re.compile(r"ποσ(?:ότητα|ότης)\s*[:=]?\s*(\d{1,6})", re.I),
    re.compile(r"(\d{1,6})\s*(?:τεμάχια|τεμ\.?|μονάδες|pcs\b)", re.I),
    re.compile(r"(\d{1,6})\s*(?:γραβάτες|φουλάρια|κλιματιστικά|υπολογιστές|laptops?|φαναράκια|καρέκλες|εκτυπωτές|οθόνες)", re.I),
)
BTU_RE = re.compile(r"(\d{1,2}(?:[.]\d{3})?|\d{4,5})\s*BTU", re.I)
DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")
RANGE_RE = re.compile(r"(?:από\s*)?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*(?:έως|ως|μέχρι|-)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I)

STOP = {
    "αποφαση", "εγκριση", "επικυρωση", "πρακτικο", "πρακτικου", "συμβαση", "συμβασης",
    "προμηθεια", "υπηρεσιων", "υπηρεσια", "αναθεση", "απευθειας", "διαπραγματευση",
    "χωρις", "προηγουμενη", "δημοσιευση", "δαπανη", "δαπανης", "παροχη", "συμφωνα",
    "διαταξεις", "αρθρου", "γενικου", "νοσοκομειου", "δημου", "φορεα", "θεμα", "και",
    "της", "του", "των", "για", "στο", "στη", "στην", "απο", "εως", "ετος", "μηνες",
}
CATEGORY_RULES = (
    ("cleaning", ("καθαρισμ", "καθαριοτητα")),
    ("food_service", ("σιτιση", "φαγητ", "εστιασ", "τροφιμ", "γευμα")),
    ("medical_waste", ("ιατρικ", "αποβλητ", "εααμ", "μεα")),
    ("air_conditioner", ("κλιματιστικ", "air condition", "btu")),
    ("computer", ("φορητ", "υπολογιστ", "laptop", "οθον", "εκτυπωτ")),
    ("apparel_gifts", ("γραβατ", "φουλαρ", "αναμνηστικ", "δωρ", "φαναρακ")),
    ("chemicals", ("αντιδραστηρ", "χημικ", "reagent")),
    ("construction", ("εργο", "κατασκευ", "ανακατασκευ", "οδοποι", "ασφαλτο")),
    ("software", ("λογισμικ", "πληροφοριακ", "software", "εφαρμογ")),
    ("transport", ("μεταφορ", "οχημα", "καυσιμ")),
)

@dataclass
class Seed:
    ada: str
    lanes: set[str] = field(default_factory=set)
    subjects: list[str] = field(default_factory=list)
    score: int = 0

@dataclass
class Record:
    ada: str
    url: str
    organization_id: str
    organization: str
    subject: str
    issue_date: str | None
    publish_date: str | None
    status: str
    corrected: bool
    private: bool
    category: str
    signature: str
    amount: float | None
    amount_basis: str
    supplier_key: str
    supplier_name: str
    cpv: str
    adams: set[str]
    related_adas: set[str]
    explicit_single_bid: bool
    explicit_no_publication: bool
    explicit_direct_award: bool
    explicit_emergency: bool
    service_start: str | None
    service_end: str | None
    quantity: int | None
    unit_price: float | None
    unit_price_source: str
    spec: str
    modification_rank: int
    focused_excerpt: str
    lanes: set[str]

    @property
    def current(self) -> bool:
        return self.status == "PUBLISHED" and not self.corrected and not self.private


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join("".join(ch for ch in text if unicodedata.category(ch) != "Mn").split())


def compact(value: Any, limit: int = 700) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("€", "").replace("EUR", "").replace("eur", "").replace(" ", "")
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        result = float(text)
    except ValueError:
        return None
    return result if result >= 0 else None


def ms_date(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_date(value: str) -> date | None:
    match = DATE_RE.fullmatch(value.strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def request(session: requests.Session, url: str, *, params: dict[str, Any] | None = None, timeout: int = 50) -> requests.Response:
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


def pdf_text(content: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="manual-diverse-") as tmp:
        pdf = Path(tmp) / "doc.pdf"
        txt = Path(tmp) / "doc.txt"
        pdf.write_bytes(content)
        done = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(txt)], capture_output=True, timeout=70, check=False)
        if done.returncode != 0 or not txt.exists():
            return ""
        return txt.read_text(encoding="utf-8", errors="replace")[:260_000]


def category(text: str) -> str:
    value = fold(text)
    for label, terms in CATEGORY_RULES:
        if any(term in value for term in terms):
            return label
    return "other"


def signature(subject: str, cat: str) -> str:
    tokens: list[str] = []
    for token in re.findall(r"[a-zα-ω0-9]+", fold(subject)):
        if len(token) < 4 or token.isdigit() or token in STOP:
            continue
        if token not in tokens:
            tokens.append(token)
    return cat + ":" + ":".join(tokens[:9])


def focus_document(subject: str, text: str) -> str:
    if not text:
        return ""
    normalized_text = fold(text)
    tokens = [t for t in re.findall(r"[a-zα-ω0-9]+", fold(subject)) if len(t) >= 6 and t not in STOP]
    anchors: list[tuple[int, str]] = []
    for token in tokens[:12]:
        pos = normalized_text.find(token)
        if pos >= 0:
            anchors.append((pos, token))
    if not anchors:
        return text[:24_000]
    anchors.sort()
    center = anchors[0][0]
    start = max(0, center - 5_000)
    end = min(len(text), center + 22_000)
    focused = text[start:end]
    # Agenda minutes often contain many unrelated subjects. Stop at the next explicit subject marker.
    after = focused[2_000:]
    next_topic = re.search(r"\n\s*(?:ΘΕΜΑ|Θέμα)\s+(?:Η\.?Δ\.?\s*)?(?:Νο\s*)?\d+", after)
    if next_topic:
        focused = focused[: 2_000 + next_topic.start()]
    return focused


def metadata_amount(detail: dict[str, Any]) -> tuple[float | None, str]:
    extra = detail.get("extraFieldValues") if isinstance(detail.get("extraFieldValues"), dict) else {}
    for container in (extra, detail):
        if not isinstance(container, dict):
            continue
        for key in ("amountWithVAT", "totalAmountWithVAT", "awardAmount", "approvedAmount", "budgetAmount", "amount", "totalAmount"):
            raw = container.get(key)
            if isinstance(raw, dict):
                raw = raw.get("amount") or raw.get("value")
            amount = parse_money(raw)
            if amount and amount > 0:
                return amount, "official_metadata"
    return None, "unknown"


def supplier(detail: dict[str, Any], focused: str) -> tuple[str, str]:
    extra = detail.get("extraFieldValues") if isinstance(detail.get("extraFieldValues"), dict) else {}
    persons = extra.get("person")
    if isinstance(persons, list):
        for item in persons:
            if not isinstance(item, dict):
                continue
            name = compact(item.get("name"), 180)
            afm = re.sub(r"\D", "", str(item.get("afm") or ""))
            if len(afm) == 9:
                return name, "afm:" + hashlib.sha256(afm.encode()).hexdigest()[:16]
            if name:
                return name, "name:" + fold(name)[:90]
    match = AFM_RE.search(focused)
    if match:
        afm = match.group(1)
        left = focused[max(0, match.start() - 260):match.start()]
        name_match = re.search(r"(?:εταιρε(?:ία|ιας)|αναδόχ(?:ου|ος)|προμηθευτ(?:ή|ης))\s*[:\-]?\s*[«\"]?([^\n;,.]{3,150})", left, re.I)
        return compact(name_match.group(1), 180) if name_match else "", "afm:" + hashlib.sha256(afm.encode()).hexdigest()[:16]
    return "", ""


def quantity_price(focused: str, amount: float | None, cat: str) -> tuple[int | None, float | None, str, str]:
    quantities: list[int] = []
    for pattern in QTY_PATTERNS:
        for match in pattern.finditer(focused):
            value = int(match.group(1))
            if 1 <= value <= 200_000:
                quantities.append(value)
    explicit = [parse_money(m.group(1)) for m in UNIT_PRICE_RE.finditer(focused)]
    explicit = [v for v in explicit if v and 0 < v < 1_000_000]
    qty = statistics.mode(quantities) if quantities else None
    if explicit:
        unit = statistics.median(explicit)
        source = "explicit_unit_price"
    elif qty and amount and amount > 0:
        unit = amount / qty
        source = "metadata_amount_divided_by_quantity"
    else:
        unit = None
        source = ""
    spec = ""
    if cat == "air_conditioner":
        btus: list[int] = []
        for match in BTU_RE.finditer(focused):
            raw = match.group(1).replace(".", "")
            value = int(raw)
            if 5_000 <= value <= 100_000:
                btus.append(value)
        if btus:
            spec = f"{statistics.mode(btus)}BTU"
    return qty, unit, source, spec


def service_period(focused: str) -> tuple[str | None, str | None]:
    match = RANGE_RE.search(focused)
    if not match:
        return None, None
    left, right = parse_date(match.group(1)), parse_date(match.group(2))
    return (left.isoformat() if left else None, right.isoformat() if right else None)


def inspect(session: requests.Session, seed: Seed) -> Record | None:
    encoded = quote(seed.ada, safe="")
    response = request(session, DETAIL.format(ada=encoded))
    if not response.ok:
        return None
    detail = response.json()
    if not isinstance(detail, dict):
        return None
    document_url = str(detail.get("documentUrl") or DOC.format(ada=encoded))
    pdf_response = request(session, document_url, timeout=70)
    text = pdf_text(pdf_response.content) if pdf_response.ok and "pdf" in pdf_response.headers.get("content-type", "").casefold() else ""
    subject = compact(detail.get("subject"), 1_200)
    focused = focus_document(subject, text)
    joined = subject + "\n" + focused
    value = fold(joined)
    cat = category(subject + " " + focused[:12_000])
    amount, basis = metadata_amount(detail)
    if amount is None:
        amounts = [parse_money(m.group(1)) for m in MONEY_RE.finditer(focused)]
        amounts = [v for v in amounts if v and v >= 1]
        if amounts:
            # PDF max is only for reading priority; it is never used for a mismatch or unit price.
            amount, basis = max(amounts), "pdf_max_reading_only"
    supplier_name, supplier_key = supplier(detail, focused)
    extra = detail.get("extraFieldValues") if isinstance(detail.get("extraFieldValues"), dict) else {}
    cpv_raw = extra.get("cpv")
    cpv = compact(cpv_raw, 120)
    adams = {m.group(0).upper() for m in ADAM_RE.finditer(joined)}
    related = {m.group(0).upper() for m in ADA_RE.finditer(json.dumps(extra, ensure_ascii=False, default=str))}
    start, end = service_period(focused)
    qty, unit, unit_source, spec = quantity_price(focused, amount if basis == "official_metadata" else None, cat)
    mod_rank = 3 if any(x in value for x in ("3η τροποποιηση", "τριτη τροποποιηση", "3ος απε", "3ου απε")) else 2 if any(x in value for x in ("2η τροποποιηση", "δευτερη τροποποιηση", "2ος απε", "2ου απε")) else 1 if "τροποποιηση" in value or "απε" in value else 0
    return Record(
        ada=seed.ada,
        url=document_url,
        organization_id=str(detail.get("organizationId") or ""),
        organization=compact(detail.get("organizationLabel") or detail.get("organization"), 250),
        subject=subject,
        issue_date=ms_date(detail.get("issueDate")),
        publish_date=ms_date(detail.get("publishTimestamp")),
        status=str(detail.get("status") or ""),
        corrected=bool(detail.get("correctedVersionId")),
        private=bool(detail.get("privateData")),
        category=cat,
        signature=signature(subject, cat),
        amount=amount,
        amount_basis=basis,
        supplier_key=supplier_key,
        supplier_name=supplier_name,
        cpv=cpv,
        adams=adams,
        related_adas=related,
        explicit_single_bid=any(x in value for x in ("μοναδικη προσφορα", "μια προσφορα", "ενας προσφερων", "μονο μια προσφορα")),
        explicit_no_publication="χωρις προηγουμενη δημοσιευση" in value,
        explicit_direct_award="απευθειας αναθεση" in value,
        explicit_emergency=any(x in value for x in ("κατεπειγουσα αναγκη", "λογω κατεπειγοντος", "εκτακτη αναγκη")),
        service_start=start,
        service_end=end,
        quantity=qty,
        unit_price=unit,
        unit_price_source=unit_source,
        spec=spec,
        modification_rank=mod_rank,
        focused_excerpt=compact(focused, 2_800),
        lanes=set(seed.lanes),
    )


class DSU:
    def __init__(self, values: list[str]) -> None:
        self.parent = {v: v for v in values}
    def find(self, value: str) -> str:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]
    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def collapse(records: list[Record]) -> list[Record]:
    dsu = DSU([r.ada for r in records])
    buckets: dict[str, list[str]] = defaultdict(list)
    for r in records:
        for adam in r.adams:
            buckets["adam:" + adam].append(r.ada)
        for related in r.related_adas:
            if related in dsu.parent:
                buckets["ada:" + related].extend([r.ada, related])
        if r.issue_date and r.amount and r.amount_basis == "official_metadata":
            buckets[f"exact:{r.organization_id}:{r.issue_date}:{r.amount:.2f}:{r.signature}"].append(r.ada)
    for values in buckets.values():
        for value in values[1:]:
            dsu.union(values[0], value)
    grouped: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        grouped[dsu.find(r.ada)].append(r)
    representatives: list[Record] = []
    for items in grouped.values():
        representatives.append(max(items, key=lambda r: (bool(r.supplier_key), r.amount_basis == "official_metadata", bool(r.unit_price), len(r.adams), r.publish_date or "")))
    return representatives


def similarity(a: Record, b: Record) -> float:
    if a.category != b.category:
        return 0.0
    left = set(a.signature.split(":" )[1:])
    right = set(b.signature.split(":" )[1:])
    if not left or not right:
        return 0.3
    return len(left & right) / len(left | right)


def record_dict(r: Record) -> dict[str, Any]:
    return {
        "ada": r.ada, "official_url": r.url, "organization_id": r.organization_id,
        "organization": r.organization, "subject": r.subject, "issue_date": r.issue_date,
        "publish_date": r.publish_date, "category": r.category, "signature": r.signature,
        "amount_eur": round(r.amount, 2) if r.amount is not None else None,
        "amount_basis": r.amount_basis, "supplier_name": r.supplier_name,
        "supplier_key_hash": r.supplier_key, "cpv": r.cpv, "adams": sorted(r.adams),
        "single_bid": r.explicit_single_bid, "without_publication": r.explicit_no_publication,
        "direct_award": r.explicit_direct_award, "emergency": r.explicit_emergency,
        "service_start": r.service_start, "service_end": r.service_end,
        "quantity": r.quantity, "unit_price_eur": round(r.unit_price, 2) if r.unit_price else None,
        "unit_price_source": r.unit_price_source, "spec": r.spec, "modification_rank": r.modification_rank,
        "focused_excerpt": r.focused_excerpt,
    }


def build_candidates(records: list[Record]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    # 1. Competition: explicit single bid, not merely a search hit.
    for r in records:
        if not r.explicit_single_bid:
            continue
        score = 58
        reasons = ["Το συγκεκριμένο επίσημο τμήμα του PDF αναφέρει μία/μοναδική προσφορά."]
        if r.amount and r.amount_basis == "official_metadata" and r.amount >= 100_000:
            score += 8
            reasons.append(f"Επίσημο ποσό €{r.amount:,.2f}.")
        if r.explicit_no_publication or r.explicit_direct_award:
            score += 7
            reasons.append("Η ίδια πράξη χρησιμοποιεί και μη ανοικτή διαδικασία.")
        candidates.append({"type": "explicit_single_bid", "score": min(score, 78), "families": ["competition"], "reasons": reasons, "records": [record_dict(r)]})

    # 2. Service began materially before the decision date.
    for r in records:
        if not r.issue_date or not r.service_start:
            continue
        issue, start = date.fromisoformat(r.issue_date), date.fromisoformat(r.service_start)
        lag = (issue - start).days
        if lag < 21:
            continue
        score = 68 + min(12, lag // 30)
        reasons = [f"Η δηλωμένη περίοδος υπηρεσίας αρχίζει {lag} ημέρες πριν από την ημερομηνία της απόφασης."]
        if r.amount and r.amount_basis == "official_metadata" and r.amount >= 30_000:
            score += 5
            reasons.append(f"Επίσημο ποσό €{r.amount:,.2f}.")
        candidates.append({"type": "service_before_decision", "score": min(score, 85), "families": ["timeline"], "reasons": reasons, "records": [record_dict(r)]})

    # 3. Repeated noncompetitive same supplier/object. Require distinct collapsed records.
    grouped: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
    for r in records:
        if r.supplier_key and (r.explicit_direct_award or r.explicit_no_publication or r.explicit_emergency):
            grouped[(r.organization_id, r.supplier_key, r.category)].append(r)
    for key, items in grouped.items():
        items = sorted(items, key=lambda r: r.issue_date or "")
        close: list[Record] = []
        for r in items:
            if not close or max(similarity(r, x) for x in close) >= 0.25:
                close.append(r)
        if len(close) < 3:
            continue
        values = [r.amount for r in close if r.amount and r.amount_basis == "official_metadata"]
        score = 68 + min(14, 4 * (len(close) - 3))
        reasons = [f"{len(close)} διαφορετικές συμβατικές αλυσίδες ίδιου φορέα, αναδόχου και κατηγορίας με μη ανοικτή/εξαιρετική διαδικασία."]
        if values and sum(values) >= 100_000:
            score += 6
            reasons.append(f"Γνωστή αθροιστική αξία €{sum(values):,.2f}.")
        candidates.append({"type": "supplier_concentration_noncompetitive", "score": min(score, 90), "families": ["supplier_pattern", "procedure_pattern"], "reasons": reasons, "records": [record_dict(r) for r in close[:8]]})

    # 4. Possible fragmentation: at least three direct awards, same supplier/object, amounts near 30k.
    for key, items in grouped.items():
        near = [r for r in items if r.explicit_direct_award and r.amount_basis == "official_metadata" and r.amount and 15_000 <= r.amount <= 30_000]
        if len(near) < 3:
            continue
        near.sort(key=lambda r: r.issue_date or "")
        total = sum(r.amount or 0 for r in near)
        score = 75 + min(10, 2 * (len(near) - 3))
        reasons = [f"{len(near)} διαφορετικές απευθείας αναθέσεις προς ίδιο ανάδοχο και ομοειδές αντικείμενο, όλες €15k–€30k.", f"Αθροιστική επίσημη αξία €{total:,.2f}."]
        candidates.append({"type": "possible_fragmentation", "score": min(score, 88), "families": ["threshold_pattern", "supplier_pattern"], "reasons": reasons, "records": [record_dict(r) for r in near[:8]]})

    # 5. Repeated emergency over time, avoiding one incident represented by many documents.
    emergency_groups: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for r in records:
        if r.explicit_emergency:
            emergency_groups[(r.organization_id, r.category)].append(r)
    for key, items in emergency_groups.items():
        if len(items) < 3:
            continue
        dated = [r for r in items if r.issue_date]
        if len(dated) < 3:
            continue
        span = (max(date.fromisoformat(r.issue_date) for r in dated) - min(date.fromisoformat(r.issue_date) for r in dated)).days
        if span < 150:
            continue
        suppliers = [r.supplier_key for r in items if r.supplier_key]
        same_supplier = bool(suppliers) and max(suppliers.count(v) for v in set(suppliers)) >= 2
        score = 70 + (8 if same_supplier else 0) + min(8, len(items) - 3)
        reasons = [f"{len(items)} διαφορετικές επείγουσες αλυσίδες της ίδιας κατηγορίας σε διάστημα {span} ημερών."]
        if same_supplier:
            reasons.append("Ο ίδιος ανάδοχος εμφανίζεται επανειλημμένα.")
        candidates.append({"type": "repeated_emergency_over_time", "score": min(score, 88), "families": ["emergency_pattern"] + (["supplier_pattern"] if same_supplier else []), "reasons": reasons, "records": [record_dict(r) for r in sorted(items, key=lambda x: x.issue_date or "", reverse=True)[:8]]})

    # 6. Unit-price outliers: leave-one-out median and strict same category/spec cohort.
    unit_groups: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for r in records:
        if r.unit_price and r.quantity and r.unit_price_source in {"explicit_unit_price", "metadata_amount_divided_by_quantity"}:
            unit_groups[(r.category, r.spec or "unspecified")].append(r)
    for key, items in unit_groups.items():
        if len(items) < 4:
            continue
        for target in items:
            peers = [r.unit_price for r in items if r.ada != target.ada and r.unit_price]
            if len(peers) < 3:
                continue
            median = statistics.median(peers)
            ratio = target.unit_price / median if median else 0
            if ratio < 2.5 or target.unit_price - median < max(50, median * 0.75):
                continue
            score = 72 + min(12, int((ratio - 2.5) * 5))
            reasons = [f"Τιμή μονάδας €{target.unit_price:,.2f} έναντι leave-one-out διαμέσου €{median:,.2f} ({ratio:.2f}×), με {len(peers)} επίσημους peers ίδιας κατηγορίας/spec."]
            candidates.append({"type": "official_unit_price_outlier", "score": min(score, 86), "families": ["unit_price_comparator"], "reasons": reasons, "records": [record_dict(target)], "peer_records": [record_dict(r) for r in items if r.ada != target.ada][:5]})

    # 7. One modification lane only, requiring explicit rank >=3 and official amount.
    mods = [r for r in records if r.modification_rank >= 3 and r.amount and r.amount_basis == "official_metadata"]
    for r in mods:
        candidates.append({"type": "advanced_modification_lead", "score": 62, "families": ["contract_change"], "reasons": [f"Ρητή {r.modification_rank}η μεταβολή με επίσημο ποσό €{r.amount:,.2f}; απαιτείται ανακατασκευή αρχικής και τελικής αξίας."], "records": [record_dict(r)]})

    # Fail closed: no candidate can be called validated with a single family.
    for candidate in candidates:
        candidate["score"] = int(candidate["score"])
        candidate["status"] = "VALIDATED_REVIEW_PRIORITY" if candidate["score"] >= 80 and len(candidate.get("families") or []) >= 2 else "RESEARCH_LEAD"
    return sorted(candidates, key=lambda c: (c["score"], len(c.get("records") or [])), reverse=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    session = requests.Session()
    session.headers.update({"User-Agent": "MizAI manual diverse Diavgeia research/1.0", "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.1"})

    seeds: dict[str, Seed] = {}
    attempts: list[dict[str, Any]] = []
    for lane, terms in LANES.items():
        for term in terms:
            windows = list(YEAR_WINDOWS)
            rng.shuffle(windows)
            for start, end in windows:
                pages = [0, 1, rng.choice([2, 3, 4, 5])]
                for page in dict.fromkeys(pages):
                    response = request(session, SEARCH, params={"term": term, "page": page, "size": PAGE_SIZE, "from_issue_date": start, "to_issue_date": end})
                    if not response.ok:
                        attempts.append({"lane": lane, "term": term, "window": [start, end], "page": page, "status": response.status_code, "count": 0})
                        continue
                    payload = response.json()
                    decisions = payload.get("decisions") if isinstance(payload, dict) else []
                    decisions = decisions if isinstance(decisions, list) else []
                    attempts.append({"lane": lane, "term": term, "window": [start, end], "page": page, "status": 200, "count": len(decisions)})
                    for raw in decisions:
                        if not isinstance(raw, dict):
                            continue
                        ada = str(raw.get("ada") or "").strip()
                        if not ada:
                            continue
                        seed = seeds.setdefault(ada, Seed(ada=ada))
                        seed.lanes.add(lane)
                        seed.subjects.append(compact(raw.get("subject"), 500))
                        seed.score = max(seed.score, {"competition": 32, "unit_price": 28, "timeline": 27, "emergency": 24, "direct_award": 20, "modification": 15}[lane])
                    if len(decisions) < PAGE_SIZE:
                        break
                    time.sleep(SLEEP)

    # Diversity quota before PDF reading. Modifications receive the smallest quota.
    lane_quota = {"competition": 55, "unit_price": 75, "timeline": 45, "emergency": 45, "direct_award": 65, "modification": 15}
    chosen: dict[str, Seed] = {}
    for lane in ("unit_price", "competition", "timeline", "direct_award", "emergency", "modification"):
        pool = [s for s in seeds.values() if lane in s.lanes]
        rng.shuffle(pool)
        pool.sort(key=lambda s: (s.score, len(s.lanes)), reverse=True)
        for seed in pool[: lane_quota[lane]]:
            chosen.setdefault(seed.ada, seed)
            if len(chosen) >= MAX_DEEP:
                break
        if len(chosen) >= MAX_DEEP:
            break

    inspected: list[Record] = []
    failures: list[dict[str, str]] = []
    for index, seed in enumerate(chosen.values(), 1):
        try:
            record = inspect(session, seed)
            if record:
                inspected.append(record)
        except Exception as exc:
            failures.append({"ada": seed.ada, "error": type(exc).__name__, "message": str(exc)[:240]})
        if index % 10 == 0:
            print(f"inspected {index}/{len(chosen)}", flush=True)
        time.sleep(SLEEP)

    current = [r for r in inspected if r.current]
    representatives = collapse(current)
    candidates = build_candidates(representatives)

    # Enforce diversity in displayed results: max one candidate per type in the primary list.
    diverse: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for candidate in candidates:
        if candidate["type"] in seen_types:
            continue
        diverse.append(candidate)
        seen_types.add(candidate["type"])
        if len(diverse) >= 8:
            break

    result = {
        "status": "completed" if inspected else "source_failure",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "coverage": {
            "metadata_records": len(seeds), "selected_for_pdf": len(chosen), "inspected": len(inspected),
            "current_decisions": len(current), "collapsed_chains": len(representatives),
            "candidate_count": len(candidates), "failures": failures, "attempts": attempts,
        },
        "diverse_top_results": diverse,
        "all_candidates": candidates[:60],
        "method_notes": [
            "Existing MizAI scoring rules were not used.",
            "Search terms were discovery-only and never evidence.",
            "Agenda PDFs were restricted to the subject-specific section before extracting signals.",
            "One result per pattern type is shown to prevent a single family from dominating.",
            "Single-family findings remain research leads even when numerically high.",
        ],
    }
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["rank\tstatus\tscore\ttype\tadas\treasons"]
    for idx, item in enumerate(diverse, 1):
        adas = ",".join(r.get("ada", "") for r in item.get("records") or [])
        lines.append("\t".join([str(idx), item["status"], str(item["score"]), item["type"], adas, " | ".join(item.get("reasons") or [])]))
    (OUT / "diverse-results.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"metadata": len(seeds), "inspected": len(inspected), "chains": len(representatives), "candidates": len(candidates), "diverse": len(diverse)}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
