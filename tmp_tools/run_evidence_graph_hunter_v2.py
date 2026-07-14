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
from typing import Any, Iterable
from urllib.parse import quote

import requests

BASE = "https://diavgeia.gov.gr"
SEARCH_URL = BASE + "/luminapi/opendata/search"
DETAIL_URL = BASE + "/luminapi/api/decisions/{ada}"
DOC_URL = BASE + "/doc/{ada}"
OUT = Path("evidence-graph-v2-output")
SEED = 5600716
PAGE_SIZE = 100
MAX_DEEP = 220
REQUEST_SLEEP = 0.16
TODAY = date(2026, 7, 14)

YEAR_WINDOWS = (
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
    ("2026-01-01", "2026-07-14"),
)

LANES: dict[str, tuple[str, ...]] = {
    "competition": ("μοναδική προσφορά", "μία προσφορά", "ένας προσφέρων"),
    "procedure": ("απευθείας ανάθεση", "χωρίς προηγούμενη δημοσίευση"),
    "emergency": ("κατεπείγουσα ανάγκη", "λόγω κατεπείγοντος", "έκτακτη ανάγκη"),
    "timeline": ("αναδρομική ισχύ", "παρασχεθείσες υπηρεσίες", "τακτοποίηση οφειλής"),
    "modification": (
        "5η τροποποίηση σύμβασης",
        "4η τροποποίηση σύμβασης",
        "3η τροποποίηση σύμβασης",
        "παράταση σύμβασης",
        "3ος ΑΠΕ",
    ),
    "unit_price": (
        "τιμή μονάδας",
        "κλιματιστικά",
        "air condition",
        "φορητοί υπολογιστές",
        "laptop",
        "γραβάτες",
        "φουλάρια",
        "υγρό οξυγόνο",
        "χημικά αντιδραστήρια",
        "καρέκλες",
        "εκτυπωτές",
    ),
}

LANE_QUOTAS = {
    "competition": 48,
    "procedure": 50,
    "emergency": 38,
    "timeline": 32,
    "modification": 18,
    "unit_price": 64,
}

# Only used for novelty ranking and regression checks, never as discovery evidence.
PREVIOUS_ADAS = {
    "ΨΔΘΔΟΡ1Π-Β28",
    "97ΤΖΟΡ1Π-Η0Θ",
    "Ρ6ΤΡΟΡ1Π-ΖΚΩ",
    "Ω873469076-7ΒΩ",
    "9ΕΥΠ469076-Λ1Ψ",
    "Ρ145469ΗΤ5-ΖΨ5",
}
TIMELINE_REGRESSION_ADA = "ΕΞ2ΞΩΚΑ-Δ3Β"

ADAM_RE = re.compile(r"\b\d{2}(?:REQ|PROC|AWRD|SYMV|PAY)\d{9}\*?\b", re.I)
ADA_RE = re.compile(r"\b[0-9Α-Ω]{4,12}-[0-9Α-Ω]{3}\b", re.I)
AFM_RE = re.compile(r"(?:Α\.?Φ\.?Μ\.?|AFM)\s*[:#]?\s*(\d{9})", re.I)
MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)",
    re.I,
)
DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")
DATE_RANGE_RE = re.compile(
    r"(?:από\s*)?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*(?:έως|ως|μέχρι|-)\s*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    re.I,
)
CONTRACT_REF_RE = re.compile(
    r"(?:σύμβαση(?:ς)?|συμφωνητικ(?:ό|ου))\s*(?:με\s*)?"
    r"(?:αρ\.?|αριθ\.?|υπ\.?\s*αρ\.?)?\s*[:#]?\s*([A-Za-zΑ-Ω0-9./-]{5,45})",
    re.I,
)
UNIT_PRICE_RE = re.compile(
    r"(?:τιμή\s*μονάδ(?:ας|ος)|ανά\s*τεμάχιο|τιμή\s*ανά\s*(?:m3|m³|μονάδα)|"
    r"/\s*(?:τεμ\.?|m3|m³))\s*[:=]?\s*"
    r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ)?",
    re.I,
)
QTY_RE = re.compile(
    r"(\d{1,6}(?:[.,]\d+)?)\s*(m3|m³|τεμάχια|τεμ\.?|μονάδες|μήνες|"
    r"δωμάτια|κιλά|kg|λίτρα|lt|ώρες)",
    re.I,
)
BTU_RE = re.compile(r"(\d{1,2}(?:[.]\d{3})?|\d{4,5})\s*BTU", re.I)

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cleaning", ("καθαρισμ", "καθαριοτητα")),
    ("food_service", ("σιτιση", "φαγητ", "εστιασ", "τροφιμ", "γευμα")),
    ("medical_waste", ("ιατρικ", "νοσοκομειακ", "αποβλητ", "εααμ", "μεα")),
    ("medical_gases", ("υγρο οξυγονο", "ιατρικ αερι", "φαρμακευτικ οξυγονο")),
    ("air_conditioner", ("κλιματιστικ", "air condition", "btu")),
    ("computer", ("φορητ", "υπολογιστ", "laptop", "οθον", "εκτυπωτ")),
    ("apparel_gifts", ("γραβατ", "φουλαρ", "αναμνηστικ", "δωρ")),
    ("chemicals", ("αντιδραστηρ", "χημικ", "reagent")),
    ("construction", ("εργο", "κατασκευ", "ανακατασκευ", "οδοποι", "ασφαλτο", "επισκευη σχολ")),
    ("software", ("λογισμικ", "πληροφοριακ", "software", "εφαρμογ")),
    ("lodging", ("διανυκτερευ", "ξενοδοχει", "καταλυμα", "δωματι")),
    ("fuel", ("καυσιμ", "βενζιν", "πετρελαι", "λιπαντικ")),
)

STOPWORDS = {
    "αποφαση", "εγκριση", "επικυρωση", "πρακτικο", "πρακτικου", "συμβαση", "συμβασης",
    "προμηθεια", "υπηρεσιων", "υπηρεσια", "αναθεση", "απευθειας", "διαπραγματευση",
    "χωρις", "προηγουμενη", "δημοσιευση", "δαπανη", "δαπανης", "παροχη", "συμφωνα",
    "διαταξεις", "αρθρου", "γενικου", "νοσοκομειου", "δημου", "φορεα", "θεμα", "και",
    "της", "του", "των", "για", "στο", "στη", "στην", "απο", "εως", "ετος", "μηνες",
}

AMOUNT_KEY_ROLES = {
    "awardAmount": "award_total",
    "approvedAmount": "approved_total",
    "budget": "budget_total",
    "budgetAmount": "budget_total",
    "contractAmount": "contract_total",
    "paymentAmount": "payment_installment",
    "amount": "declared_amount",
    "totalAmount": "declared_total",
    "amountWithVAT": "declared_total",
    "totalAmountWithVAT": "declared_total",
}

AMOUNT_ROLE_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget_total", ("προϋπολογ", "εκτιμωμενη αξια", "προυπολογ")),
    ("modification_delta", ("αυξηση", "προσθετη δαπανη", "επιπλεον ποσο", "διαφορα τιμηματοσ")),
    ("final_cumulative_value", ("τελικη αξια", "διαμορφωνεται", "συνολικη αξια μετα", "νεο συμβατικο τιμημα")),
    ("contract_total", ("συμβατικη αξια", "συμβατικο τιμημα", "αξια συμβασησ")),
    ("award_total", ("κατακυρωση", "οικονομικη προσφορα", "συνολικη τιμη")),
    ("payment_installment", ("πληρωμη", "τιμολογιο", "ενταλμα", "εξοφληση")),
    ("remaining_balance", ("υπολοιπο", "λοιπο πιστωσησ")),
    ("unit_price", ("τιμη μοναδασ", "ανα τεμαχιο", "/m3", "/m³")),
)

SERVICE_ROLE_TERMS = (
    "παροχη των υπηρεσιων",
    "διαρκεια τησ συμβασησ",
    "χρονικη διαρκεια",
    "ισχυς τησ συμβασησ",
    "εκτελεση τησ συμβασησ",
    "παραταση τησ συμβασησ",
    "παροχη υπηρεσιων",
    "θα παρεχεται",
)
PROGRAMME_ROLE_TERMS = (
    "χρηματοδοτηση",
    "προγραμμα",
    "πραξη",
    "εσπα",
    "ππα",
    "mis",
    "ενταγμεν",
    "προγραμματικη περιοδο",
)


@dataclass(frozen=True)
class Fact:
    fact_type: str
    value: Any
    role: str
    unit: str
    scope: str
    source_ada: str
    source_page: int | None
    source_excerpt: str
    confidence: float
    dependency_group: str
    basis: str = ""


@dataclass
class Seed:
    ada: str
    lanes: set[str] = field(default_factory=set)
    subject: str = ""
    discovery_score: int = 0


@dataclass
class EvidenceRecord:
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
    category: str
    signature: str
    supplier_name: str
    supplier_key: str
    cpv: str
    adams: set[str]
    related_adas: set[str]
    contract_refs: set[str]
    facts: list[Fact]
    focused_pages: list[int]
    lanes: set[str]

    @property
    def current(self) -> bool:
        return self.status == "PUBLISHED" and not self.corrected and not self.private


@dataclass
class Chain:
    chain_id: str
    records: list[EvidenceRecord]

    @property
    def representative(self) -> EvidenceRecord:
        return max(
            self.records,
            key=lambda record: (
                bool(record.supplier_key),
                sum(f.confidence for f in record.facts),
                len(record.adams) + len(record.contract_refs),
                record.publish_date or "",
            ),
        )

    @property
    def adas(self) -> set[str]:
        return {record.ada for record in self.records}


class DSU:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join(
        "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").split()
    )


def compact(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_money(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = (
        str(raw)
        .replace("€", "")
        .replace("EUR", "")
        .replace("eur", "")
        .replace(" ", "")
    )
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None


def ms_date(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_date(raw: str) -> date | None:
    match = DATE_RE.fullmatch(raw.strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def request(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 55,
) -> requests.Response:
    last: Exception | None = None
    for attempt in range(5):
        try:
            response = session.get(
                url,
                params=params,
                timeout=timeout,
                allow_redirects=True,
            )
            if response.status_code in {429, 502, 503, 504}:
                time.sleep(2 ** attempt)
                continue
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {last}")


def extract_pages(content: bytes) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="evidence-graph-v2-") as tmp:
        pdf = Path(tmp) / "document.pdf"
        text = Path(tmp) / "document.txt"
        pdf.write_bytes(content)
        completed = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(text)],
            capture_output=True,
            timeout=75,
            check=False,
        )
        if completed.returncode != 0 or not text.exists():
            return []
        raw = text.read_text(encoding="utf-8", errors="replace")
        pages = raw.split("\f")
        return [page[:80_000] for page in pages if page.strip()]


def object_category(text: str) -> str:
    value = fold(text)
    for category, terms in CATEGORY_RULES:
        if any(term in value for term in terms):
            return category
    return "other"


def object_signature(subject: str, category: str) -> str:
    tokens: list[str] = []
    for token in re.findall(r"[a-zα-ω0-9]+", fold(subject)):
        if len(token) < 4 or token.isdigit() or token in STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return f"{category}:" + ":".join(tokens[:10])


def subject_tokens(subject: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zα-ω0-9]+", fold(subject))
        if len(token) >= 6 and token not in STOPWORDS
    ][:18]


def select_focused_pages(subject: str, pages: list[str]) -> list[tuple[int, str]]:
    if not pages:
        return []
    tokens = subject_tokens(subject)
    exact = fold(subject)[:120]
    scored: list[tuple[float, int]] = []
    for index, page in enumerate(pages, start=1):
        value = fold(page)
        token_hits = sum(token in value for token in tokens)
        exact_bonus = 10 if exact and exact in value else 0
        procurement_bonus = sum(
            phrase in value
            for phrase in (
                "μοναδικη προσφορα",
                "απευθειασ αναθεση",
                "κατεπειγουσα αναγκη",
                "τροποποιηση συμβασησ",
                "τιμη μοναδασ",
                "συνολικη τιμη",
            )
        )
        scored.append((token_hits * 2 + exact_bonus + procurement_bonus, index))
    scored.sort(reverse=True)
    selected: set[int] = set()
    for score, index in scored[:2]:
        if score <= 0:
            continue
        selected.add(index)
        if index > 1:
            selected.add(index - 1)
        if index < len(pages):
            selected.add(index + 1)
    if not selected:
        selected = {1}
    return [(index, pages[index - 1]) for index in sorted(selected)]


def sentence_excerpt(text: str, start: int, end: int, radius: int = 260) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return compact(text[left:right], 650)


def infer_vat_basis(context: str) -> str:
    value = fold(context)
    if any(term in value for term in ("με φπα", "συμπεριλαμβανομενου φπα", "με το φπα")):
        return "gross"
    if any(term in value for term in ("χωρισ φπα", "ανευ φπα", "πλεον φπα")):
        return "net"
    return "unknown"


def metadata_amount_facts(
    detail: dict[str, Any],
    ada: str,
) -> list[Fact]:
    facts: list[Fact] = []
    extra = (
        detail.get("extraFieldValues")
        if isinstance(detail.get("extraFieldValues"), dict)
        else {}
    )
    for container_name, container in (("extra", extra), ("detail", detail)):
        if not isinstance(container, dict):
            continue
        for key, role in AMOUNT_KEY_ROLES.items():
            raw = container.get(key)
            if isinstance(raw, dict):
                raw = raw.get("amount") or raw.get("value")
            amount = parse_money(raw)
            if amount is None or amount <= 0:
                continue
            facts.append(
                Fact(
                    fact_type="amount",
                    value=round(amount, 2),
                    role=role,
                    unit="EUR",
                    scope="decision",
                    source_ada=ada,
                    source_page=None,
                    source_excerpt=f"{container_name}.{key}={raw}",
                    confidence=0.96,
                    dependency_group="financial",
                    basis="official_metadata",
                )
            )
    unique: dict[tuple[str, float], Fact] = {}
    for fact in facts:
        unique[(fact.role, float(fact.value))] = fact
    return list(unique.values())


def pdf_amount_facts(
    ada: str,
    focused_pages: list[tuple[int, str]],
) -> list[Fact]:
    output: list[Fact] = []
    for page_number, page in focused_pages:
        for match in MONEY_RE.finditer(page):
            amount = parse_money(match.group(1))
            if amount is None or amount <= 0:
                continue
            context = sentence_excerpt(page, match.start(), match.end(), radius=320)
            context_folded = fold(context)
            role = ""
            for candidate_role, terms in AMOUNT_ROLE_TERMS:
                if any(term in context_folded for term in terms):
                    role = candidate_role
                    break
            if not role:
                continue
            output.append(
                Fact(
                    fact_type="amount",
                    value=round(amount, 2),
                    role=role,
                    unit="EUR",
                    scope="subject_section",
                    source_ada=ada,
                    source_page=page_number,
                    source_excerpt=context,
                    confidence=0.90,
                    dependency_group="financial",
                    basis=infer_vat_basis(context),
                )
            )
    unique: dict[tuple[str, float, str], Fact] = {}
    for fact in output:
        key = (fact.role, float(fact.value), fact.basis)
        current = unique.get(key)
        if current is None or fact.confidence > current.confidence:
            unique[key] = fact
    return list(unique.values())[:30]


def date_facts(
    ada: str,
    focused_pages: list[tuple[int, str]],
) -> list[Fact]:
    output: list[Fact] = []
    for page_number, page in focused_pages:
        for match in DATE_RANGE_RE.finditer(page):
            left = parse_date(match.group(1))
            right = parse_date(match.group(2))
            if left is None or right is None or right < left:
                continue
            context = sentence_excerpt(page, match.start(), match.end(), radius=380)
            value = fold(context)
            is_programme = any(term in value for term in PROGRAMME_ROLE_TERMS)
            is_service = any(term in value for term in SERVICE_ROLE_TERMS)
            if is_service and not is_programme:
                role = "contract_performance_period"
                confidence = 0.94
                dependency = "timeline"
            elif is_programme:
                role = "programme_period"
                confidence = 0.90
                dependency = "context"
            else:
                role = "untyped_period"
                confidence = 0.45
                dependency = "audit"
            output.append(
                Fact(
                    fact_type="date_range",
                    value={"start": left.isoformat(), "end": right.isoformat()},
                    role=role,
                    unit="date",
                    scope="subject_section",
                    source_ada=ada,
                    source_page=page_number,
                    source_excerpt=context,
                    confidence=confidence,
                    dependency_group=dependency,
                )
            )
    return output[:20]


def phrase_fact(
    *,
    ada: str,
    page_number: int,
    page: str,
    phrases: tuple[str, ...],
    fact_type: str,
    role: str,
    dependency_group: str,
    confidence: float = 0.98,
) -> Fact | None:
    value = fold(page)
    for phrase in phrases:
        normalized = fold(phrase)
        if normalized not in value:
            continue
        raw_position = page.casefold().find(phrase.casefold())
        raw_position = raw_position if raw_position >= 0 else 0
        excerpt = sentence_excerpt(page, raw_position, raw_position + len(phrase), radius=380)
        return Fact(
            fact_type=fact_type,
            value=True,
            role=role,
            unit="boolean",
            scope="subject_section",
            source_ada=ada,
            source_page=page_number,
            source_excerpt=excerpt,
            confidence=confidence,
            dependency_group=dependency_group,
        )
    return None


def procedure_and_context_facts(
    ada: str,
    focused_pages: list[tuple[int, str]],
) -> list[Fact]:
    specs = (
        (("μοναδική προσφορά", "μία προσφορά", "ένας προσφέρων", "μόνο μία προσφορά"), "competition", "single_bid", "competition"),
        (("χωρίς προηγούμενη δημοσίευση",), "procedure", "without_publication", "procedure"),
        (("απευθείας ανάθεση",), "procedure", "direct_award", "procedure"),
        (("κατεπείγουσα ανάγκη", "λόγω κατεπείγοντος", "έκτακτη ανάγκη"), "procedure", "emergency", "procedure"),
        (("αναζήτηση προσφορών στην τοπική αγορά", "μετά από αναζήτηση προσφορών"), "ordinary_explanation", "local_market_search", "falsification"),
        (("στο μειοδότη", "χαμηλότερη προσφορά", "πλέον συμφέρουσα προσφορά"), "ordinary_explanation", "lowest_bidder", "falsification"),
        (("ανοικτός ηλεκτρονικός διαγωνισμός", "ανοικτού διεθνούς ηλεκτρονικού διαγωνισμού"), "ordinary_explanation", "open_tender", "falsification"),
        (("μέχρι την ολοκλήρωση της νέας", "εκκρεμεί η ολοκλήρωση", "μέχρι την υπογραφή νέας σύμβασης"), "ordinary_explanation", "pending_replacement_tender", "falsification"),
        (("άνευ πρόσθετης οικονομικής επιβάρυνσης", "χωρίς πρόσθετη οικονομική επιβάρυνση"), "ordinary_explanation", "no_extra_cost", "falsification"),
        (("δεύτερη πρόσκληση", "επαναληπτική πρόσκληση"), "ordinary_explanation", "repeat_invitation", "falsification"),
        (("προσφορές για το σύνολο", "προσφορά για το σύνολο των ειδών", "για το σύνολο της ποσότητας"), "competition", "all_items_required", "competition"),
    )
    facts: list[Fact] = []
    for page_number, page in focused_pages:
        for phrases, fact_type, role, dependency in specs:
            fact = phrase_fact(
                ada=ada,
                page_number=page_number,
                page=page,
                phrases=phrases,
                fact_type=fact_type,
                role=role,
                dependency_group=dependency,
            )
            if fact is not None:
                facts.append(fact)
    unique: dict[tuple[str, str], Fact] = {}
    for fact in facts:
        unique[(fact.fact_type, fact.role)] = fact
    return list(unique.values())


def modification_facts(
    ada: str,
    subject: str,
    focused_pages: list[tuple[int, str]],
) -> list[Fact]:
    text = fold(subject + "\n" + "\n".join(page for _, page in focused_pages))
    patterns = (
        (5, ("5η τροποποιηση", "πεμπτη τροποποιηση")),
        (4, ("4η τροποποιηση", "τεταρτη τροποποιηση")),
        (3, ("3η τροποποιηση", "τριτη τροποποιηση", "3ος απε", "3ου απε")),
        (2, ("2η τροποποιηση", "δευτερη τροποποιηση", "2ος απε", "2ου απε")),
        (1, ("τροποποιηση συμβασησ", "παραταση συμβασησ", "ανακεφαλαιωτικοσ πινακασ")),
    )
    rank = 0
    for candidate_rank, phrases in patterns:
        if any(phrase in text for phrase in phrases):
            rank = max(rank, candidate_rank)
    if rank == 0:
        return []
    page_number = focused_pages[0][0] if focused_pages else None
    return [
        Fact(
            fact_type="contract_change",
            value=rank,
            role="modification_rank",
            unit="ordinal",
            scope="contract_chain",
            source_ada=ada,
            source_page=page_number,
            source_excerpt=compact(subject, 650),
            confidence=0.95,
            dependency_group="contract_change",
        )
    ]


def unit_price_facts(
    ada: str,
    category: str,
    focused_pages: list[tuple[int, str]],
) -> list[Fact]:
    facts: list[Fact] = []
    for page_number, page in focused_pages:
        explicit_prices = [parse_money(match.group(1)) for match in UNIT_PRICE_RE.finditer(page)]
        explicit_prices = [value for value in explicit_prices if value is not None and 0 < value < 1_000_000]
        quantities = []
        units = []
        for match in QTY_RE.finditer(page):
            raw = match.group(1).replace(".", "").replace(",", ".")
            try:
                quantity = float(raw)
            except ValueError:
                continue
            if 0 < quantity <= 1_000_000:
                quantities.append(quantity)
                units.append(match.group(2))
        if not explicit_prices or not quantities:
            continue
        price = statistics.median(explicit_prices)
        quantity = statistics.mode(quantities)
        unit_label = statistics.mode(units)
        spec = ""
        if category == "air_conditioner":
            btus = []
            for match in BTU_RE.finditer(page):
                raw = match.group(1).replace(".", "")
                value = int(raw)
                if 5_000 <= value <= 100_000:
                    btus.append(value)
            if btus:
                spec = f"{statistics.mode(btus)}BTU"
        excerpt = compact(page, 1000)
        facts.extend(
            [
                Fact("quantity", quantity, "procured_quantity", unit_label, "line_item", ada, page_number, excerpt, 0.86, "unit_price", spec),
                Fact("unit_price", round(price, 4), "explicit_unit_price", f"EUR/{unit_label}", "line_item", ada, page_number, excerpt, 0.88, "unit_price", spec),
            ]
        )
    return facts[:8]


def extract_supplier(
    detail: dict[str, Any],
    focused_pages: list[tuple[int, str]],
) -> tuple[str, str]:
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
    joined = "\n".join(page for _, page in focused_pages)
    match = AFM_RE.search(joined)
    if match:
        afm = match.group(1)
        left = joined[max(0, match.start() - 300):match.start()]
        name_match = re.search(
            r"(?:εταιρε(?:ία|ιας)|αναδόχ(?:ου|ος)|προμηθευτ(?:ή|ης))\s*[:\-]?\s*[«\"]?([^\n;,.]{3,150})",
            left,
            re.I,
        )
        name = compact(name_match.group(1), 180) if name_match else ""
        return name, "afm:" + hashlib.sha256(afm.encode()).hexdigest()[:16]
    return "", ""


def inspect_decision(session: requests.Session, seed: Seed) -> EvidenceRecord | None:
    encoded = quote(seed.ada, safe="")
    response = request(session, DETAIL_URL.format(ada=encoded))
    if not response.ok:
        return None
    detail = response.json()
    if not isinstance(detail, dict):
        return None
    document_url = str(detail.get("documentUrl") or DOC_URL.format(ada=encoded))
    pdf_response = request(session, document_url, timeout=75)
    pages: list[str] = []
    if pdf_response.ok and "pdf" in pdf_response.headers.get("content-type", "").casefold():
        pages = extract_pages(pdf_response.content)
    subject = compact(detail.get("subject"), 1200)
    focused_pages = select_focused_pages(subject, pages)
    focused_text = subject + "\n" + "\n".join(page for _, page in focused_pages)
    category = object_category(focused_text[:25_000])
    extra = detail.get("extraFieldValues") if isinstance(detail.get("extraFieldValues"), dict) else {}
    cpv_raw = extra.get("cpv")
    cpv = ",".join(compact(item, 40) for item in cpv_raw) if isinstance(cpv_raw, list) else compact(cpv_raw, 100)
    supplier_name, supplier_key = extract_supplier(detail, focused_pages)
    facts = [
        *metadata_amount_facts(detail, seed.ada),
        *pdf_amount_facts(seed.ada, focused_pages),
        *date_facts(seed.ada, focused_pages),
        *procedure_and_context_facts(seed.ada, focused_pages),
        *modification_facts(seed.ada, subject, focused_pages),
        *unit_price_facts(seed.ada, category, focused_pages),
    ]
    issue = ms_date(detail.get("issueDate"))
    published = ms_date(detail.get("publishTimestamp"))
    if issue:
        facts.append(Fact("date", issue, "decision_date", "date", "decision", seed.ada, None, "official metadata issueDate", 0.99, "timeline", "official_metadata"))
    if published:
        facts.append(Fact("date", published, "publication_date", "date", "decision", seed.ada, None, "official metadata publishTimestamp", 0.99, "transparency", "official_metadata"))
    joined = focused_text + "\n" + json.dumps(extra, ensure_ascii=False, default=str)
    adams = {match.group(0).upper() for match in ADAM_RE.finditer(joined)}
    related_adas = {match.group(0).upper() for match in ADA_RE.finditer(json.dumps(extra, ensure_ascii=False, default=str))}
    contract_refs = {
        compact(match.group(1), 60).upper()
        for match in CONTRACT_REF_RE.finditer(focused_text)
        if len(compact(match.group(1), 60)) >= 5
    }
    return EvidenceRecord(
        ada=seed.ada,
        official_url=document_url,
        organization_id=str(detail.get("organizationId") or ""),
        organization=compact(detail.get("organizationLabel") or detail.get("organization") or "", 260),
        subject=subject,
        issue_date=issue,
        publish_date=published,
        decision_type=str(detail.get("decisionTypeId") or ""),
        status=str(detail.get("status") or ""),
        corrected=bool(detail.get("correctedVersionId")),
        private=bool(detail.get("privateData")),
        category=category,
        signature=object_signature(subject, category),
        supplier_name=supplier_name,
        supplier_key=supplier_key,
        cpv=cpv,
        adams=adams,
        related_adas=related_adas,
        contract_refs=contract_refs,
        facts=facts,
        focused_pages=[page_number for page_number, _ in focused_pages],
        lanes=set(seed.lanes),
    )


def collapse_chains(records: list[EvidenceRecord]) -> list[Chain]:
    dsu = DSU(record.ada for record in records)
    identifiers: dict[str, list[str]] = defaultdict(list)
    for record in records:
        for adam in record.adams:
            identifiers["adam:" + adam].append(record.ada)
        for contract_ref in record.contract_refs:
            identifiers["contract:" + contract_ref].append(record.ada)
        for related in record.related_adas:
            if related in dsu.parent:
                identifiers["ada:" + related].extend([record.ada, related])
    for values in identifiers.values():
        for other in values[1:]:
            dsu.union(values[0], other)
    grouped: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        grouped[dsu.find(record.ada)].append(record)
    chains: list[Chain] = []
    for items in grouped.values():
        fingerprint = hashlib.sha256("|".join(sorted(record.ada for record in items)).encode()).hexdigest()[:18]
        chains.append(Chain(chain_id=fingerprint, records=items))
    return chains


def facts_by_role(record: EvidenceRecord, role: str) -> list[Fact]:
    return [fact for fact in record.facts if fact.role == role]


def has_role(record: EvidenceRecord, role: str) -> bool:
    return any(fact.role == role and fact.confidence >= 0.80 for fact in record.facts)


def best_amount(record: EvidenceRecord, allowed_roles: set[str]) -> Fact | None:
    candidates = [fact for fact in record.facts if fact.fact_type == "amount" and fact.role in allowed_roles and fact.confidence >= 0.85]
    if not candidates:
        return None
    return max(candidates, key=lambda fact: (fact.basis == "official_metadata", fact.confidence, float(fact.value)))


def similarity(left: EvidenceRecord, right: EvidenceRecord) -> float:
    if left.category != right.category:
        return 0.0
    a = set(left.signature.split(":")[1:])
    b = set(right.signature.split(":")[1:])
    if not a or not b:
        return 0.25
    return len(a & b) / len(a | b)


def serialize_fact(fact: Fact) -> dict[str, Any]:
    return {
        "fact_type": fact.fact_type,
        "value": fact.value,
        "role": fact.role,
        "unit": fact.unit,
        "scope": fact.scope,
        "source_ada": fact.source_ada,
        "source_page": fact.source_page,
        "source_excerpt": fact.source_excerpt,
        "confidence": round(fact.confidence, 3),
        "dependency_group": fact.dependency_group,
        "basis": fact.basis,
    }


def serialize_record(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "ada": record.ada,
        "official_url": record.official_url,
        "organization_id": record.organization_id,
        "organization": record.organization,
        "subject": record.subject,
        "issue_date": record.issue_date,
        "publish_date": record.publish_date,
        "decision_type": record.decision_type,
        "category": record.category,
        "signature": record.signature,
        "supplier_name": record.supplier_name,
        "supplier_key_hash": record.supplier_key,
        "cpv": record.cpv,
        "adams": sorted(record.adams),
        "contract_refs": sorted(record.contract_refs),
        "focused_pages": record.focused_pages,
        "facts": [serialize_fact(fact) for fact in record.facts],
    }


def score_case(
    *,
    evidence_quality: int,
    pattern_strength: int,
    peer_deviation: int,
    materiality: int,
    falsification_survival: int,
    families: set[str],
    evidence_roles_complete: bool,
    page_provenance: bool,
    strong_ordinary_explanation: bool,
) -> tuple[int, list[str], dict[str, int]]:
    axes = {
        "evidence_quality": max(0, min(30, evidence_quality)),
        "pattern_strength": max(0, min(25, pattern_strength)),
        "peer_deviation": max(0, min(20, peer_deviation)),
        "materiality": max(0, min(10, materiality)),
        "falsification_survival": max(0, min(15, falsification_survival)),
    }
    score = sum(axes.values())
    caps: list[tuple[int, str]] = []
    if len(families) < 2:
        caps.append((69, "μία μόνο ανεξάρτητη evidence family"))
    if not evidence_roles_complete:
        caps.append((59, "άγνωστος ή μη επαρκώς typed ρόλος ημερομηνίας/ποσού"))
    if not page_provenance:
        caps.append((49, "λείπει page-level επίσημο excerpt"))
    if strong_ordinary_explanation and len(families) < 3:
        caps.append((59, "ισχυρή φυσιολογική εξήγηση δεν έχει αντικρουστεί"))
    for cap, _ in caps:
        score = min(score, cap)
    return max(0, min(100, score)), [reason for _, reason in caps], axes


def candidate(
    *,
    primary_type: str,
    chain_ids: set[str],
    records: list[EvidenceRecord],
    families: set[str],
    reasons: list[str],
    ordinary_explanations: list[str],
    score_args: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score, caps, axes = score_case(families=families, **score_args)
    fingerprint = hashlib.sha256("|".join(sorted(chain_ids)).encode()).hexdigest()[:18]
    seen_before = any(record.ada in PREVIOUS_ADAS for record in records)
    return {
        "case_fingerprint": fingerprint,
        "primary_type": primary_type,
        "detectors": [primary_type],
        "chain_ids": sorted(chain_ids),
        "families": sorted(families),
        "review_priority": score,
        "score_axes": axes,
        "caps": caps,
        "reasons": reasons,
        "ordinary_explanations": ordinary_explanations,
        "metrics": metrics or {},
        "seen_in_previous_run": seen_before,
        "novelty_rank_score": score - (10 if seen_before else 0),
        "status": "FOUND_VALIDATED" if score >= 80 and len(families) >= 2 else "RESEARCH_LEAD",
        "records": [serialize_record(record) for record in records],
    }


def build_candidates(chains: list[Chain]) -> list[dict[str, Any]]:
    representatives = [chain.representative for chain in chains]
    chain_for_ada = {record.ada: chain for chain in chains for record in chain.records}
    output: list[dict[str, Any]] = []

    for record in representatives:
        if not record.issue_date:
            continue
        decision_date = date.fromisoformat(record.issue_date)
        periods = [fact for fact in record.facts if fact.role == "contract_performance_period" and fact.confidence >= 0.90 and fact.source_page is not None]
        for period in periods:
            start = date.fromisoformat(period.value["start"])
            lag = (decision_date - start).days
            if lag < 21:
                continue
            retroactive = "αναδρομ" in fold(period.source_excerpt)
            families = {"timeline"}
            reasons = [f"Ρητά typed περίοδος εκτέλεσης αρχίζει {lag} ημέρες πριν από την απόφαση.", f"Πηγή: σελίδα {period.source_page} του επίσημου PDF."]
            if retroactive:
                reasons.append("Το ίδιο απόσπασμα χρησιμοποιεί ρητή αναδρομική διατύπωση.")
            ordinary = ["Υπάρχει αναφορά σε ανοικτή διαδικασία."] if has_role(record, "open_tender") else []
            output.append(candidate(
                primary_type="typed_service_before_decision",
                chain_ids={chain_for_ada[record.ada].chain_id},
                records=[record],
                families=families,
                reasons=reasons,
                ordinary_explanations=ordinary,
                score_args={
                    "evidence_quality": 27,
                    "pattern_strength": 18 if lag >= 90 else 12,
                    "peer_deviation": 0,
                    "materiality": 4,
                    "falsification_survival": 8 if retroactive else 5,
                    "evidence_roles_complete": True,
                    "page_provenance": True,
                    "strong_ordinary_explanation": bool(ordinary),
                },
                metrics={"lag_days": lag},
            ))

    for record in representatives:
        single_bid_facts = facts_by_role(record, "single_bid")
        if not single_bid_facts:
            continue
        families = {"competition"}
        reasons = [f"Το επίσημο PDF αναφέρει ρητά μία/μοναδική προσφορά στη σελίδα {single_bid_facts[0].source_page}."]
        ordinary = []
        for role, explanation in (("open_tender", "Η πράξη αναφέρει ανοικτή διαδικασία."), ("repeat_invitation", "Πρόκειται για δεύτερη ή επαναληπτική πρόσκληση."), ("lowest_bidder", "Η επίσημη πράξη αναφέρει επιλογή χαμηλότερης προσφοράς.")):
            if has_role(record, role):
                ordinary.append(explanation)
        if has_role(record, "all_items_required"):
            families.add("restrictive_bundle")
            reasons.append("Το ίδιο έγγραφο απαιτεί προσφορά για το σύνολο των ειδών/ποσότητας.")
        amount = best_amount(record, {"budget_total", "award_total", "contract_total", "declared_total"})
        materiality = 0
        if amount:
            materiality = 6 if float(amount.value) >= 100_000 else 3
            reasons.append(f"Typed επίσημο οικονομικό μέγεθος: €{float(amount.value):,.2f} ({amount.role}, {amount.basis}).")
        output.append(candidate(
            primary_type="single_bid_restrictive_bundle" if "restrictive_bundle" in families else "explicit_single_bid",
            chain_ids={chain_for_ada[record.ada].chain_id},
            records=[record],
            families=families,
            reasons=reasons,
            ordinary_explanations=ordinary,
            score_args={
                "evidence_quality": 27,
                "pattern_strength": 15,
                "peer_deviation": 0,
                "materiality": materiality,
                "falsification_survival": max(2, 10 - 3 * len(ordinary)),
                "evidence_roles_complete": True,
                "page_provenance": True,
                "strong_ordinary_explanation": len(ordinary) >= 2,
            },
        ))

    grouped: dict[tuple[str, str, str], list[tuple[Chain, EvidenceRecord]]] = defaultdict(list)
    emergency_denominator: dict[tuple[str, str], int] = defaultdict(int)
    for chain in chains:
        record = chain.representative
        emergency_denominator[(record.organization_id, record.category)] += 1
        if record.supplier_key and (has_role(record, "emergency") or has_role(record, "direct_award") or has_role(record, "without_publication")):
            grouped[(record.organization_id, record.supplier_key, record.category)].append((chain, record))
    for (organization_id, supplier_key, category), values in grouped.items():
        values = sorted(values, key=lambda item: item[1].issue_date or "")
        if len(values) < 3:
            continue
        records = [record for _, record in values]
        if max(similarity(records[0], record) for record in records[1:]) < 0.20:
            continue
        dated = [date.fromisoformat(record.issue_date) for record in records if record.issue_date]
        span = (max(dated) - min(dated)).days if len(dated) >= 2 else 0
        if span < 120:
            continue
        emergency_count = sum(has_role(record, "emergency") for record in records)
        families = {"supplier_pattern", "procedure_pattern"}
        reasons = [f"{len(records)} διαφορετικές collapsed chains ίδιου φορέα, αναδόχου και κατηγορίας.", f"Το μοτίβο εκτείνεται σε {span} ημέρες."]
        if emergency_count >= 2:
            reasons.append(f"{emergency_count} chains έχουν ρητή επίκληση επείγοντος.")
        denominator = emergency_denominator[(organization_id, category)]
        sample_rate = emergency_count / denominator if denominator else None
        ordinary = []
        if any(has_role(record, "local_market_search") for record in records):
            ordinary.append("Σε τουλάχιστον μία πράξη καταγράφεται αναζήτηση στην τοπική αγορά.")
        if any(has_role(record, "lowest_bidder") for record in records):
            ordinary.append("Σε τουλάχιστον μία πράξη αναφέρεται μειοδότης/χαμηλότερη προσφορά.")
        known_amounts = [best_amount(record, {"award_total", "contract_total", "declared_total"}) for record in records]
        known_amounts = [fact for fact in known_amounts if fact is not None]
        total = sum(float(fact.value) for fact in known_amounts)
        output.append(candidate(
            primary_type="repeated_emergency_supplier" if emergency_count >= 2 else "supplier_concentration_noncompetitive",
            chain_ids={chain.chain_id for chain, _ in values},
            records=records[:8],
            families=families,
            reasons=reasons,
            ordinary_explanations=ordinary,
            score_args={
                "evidence_quality": 27,
                "pattern_strength": min(25, 16 + 3 * (len(records) - 3)),
                "peer_deviation": 5 if sample_rate is not None and sample_rate >= 0.5 else 0,
                "materiality": 6 if total >= 100_000 else 2,
                "falsification_survival": max(4, 12 - 3 * len(ordinary)),
                "evidence_roles_complete": True,
                "page_provenance": True,
                "strong_ordinary_explanation": len(ordinary) >= 2,
            },
            metrics={
                "chain_count": len(records),
                "span_days": span,
                "emergency_count": emergency_count,
                "comparable_chains_in_inspected_sample": denominator,
                "emergency_rate_in_biased_sample": round(sample_rate, 3) if sample_rate is not None else None,
                "known_typed_amount_total_eur": round(total, 2),
                "denominator_warning": "Το sample είναι discovery-biased· ο παρονομαστής δεν είναι πλήρης απογραφή.",
            },
        ))

    fragmentation_groups: dict[tuple[str, str, str], list[tuple[Chain, EvidenceRecord, Fact]]] = defaultdict(list)
    for chain in chains:
        record = chain.representative
        if not record.supplier_key or not has_role(record, "direct_award"):
            continue
        amount = best_amount(record, {"award_total", "contract_total", "approved_total", "declared_total"})
        if amount is None or not (15_000 <= float(amount.value) <= 30_000):
            continue
        fragmentation_groups[(record.organization_id, record.supplier_key, record.category)].append((chain, record, amount))
    for values in fragmentation_groups.values():
        if len(values) < 3:
            continue
        records = [record for _, record, _ in values]
        dates = [date.fromisoformat(record.issue_date) for record in records if record.issue_date]
        if len(dates) < 3 or (max(dates) - min(dates)).days > 365:
            continue
        if max(similarity(records[0], record) for record in records[1:]) < 0.25:
            continue
        total = sum(float(amount.value) for _, _, amount in values)
        output.append(candidate(
            primary_type="possible_fragmentation",
            chain_ids={chain.chain_id for chain, _, _ in values},
            records=records[:8],
            families={"threshold_pattern", "supplier_pattern"},
            reasons=[f"{len(values)} διαφορετικές απευθείας αναθέσεις προς ίδιο ανάδοχο με typed ποσά €15k–€30k.", f"Αθροιστική typed αξία €{total:,.2f} σε έως 365 ημέρες."],
            ordinary_explanations=["Απαιτείται έλεγχος αν πρόκειται για διαφορετικά lots, τοποθεσίες ή πραγματικά διακριτές ανάγκες."],
            score_args={
                "evidence_quality": 28,
                "pattern_strength": 22,
                "peer_deviation": 10,
                "materiality": 8,
                "falsification_survival": 8,
                "evidence_roles_complete": True,
                "page_provenance": all(amount.source_page is not None or amount.basis == "official_metadata" for _, _, amount in values),
                "strong_ordinary_explanation": False,
            },
            metrics={"cumulative_value_eur": round(total, 2)},
        ))

    for chain in chains:
        record = chain.representative
        change_facts = [fact for item in chain.records for fact in item.facts if fact.role == "modification_rank"]
        if not change_facts:
            continue
        max_rank = max(int(fact.value) for fact in change_facts)
        if max_rank < 3 and len(change_facts) < 3:
            continue
        amount_delta = [fact for item in chain.records for fact in item.facts if fact.role == "modification_delta" and fact.confidence >= 0.85]
        final_value = [fact for item in chain.records for fact in item.facts if fact.role == "final_cumulative_value" and fact.confidence >= 0.85]
        families = {"contract_change"}
        reasons = [f"Η chain φτάνει τουλάχιστον σε {max_rank}η τροποποίηση/ΑΠΕ."]
        if amount_delta and final_value:
            families.add("financial_change")
            reasons.append("Υπάρχουν typed ποσά τόσο για μεταβολή όσο και για τελική σωρευτική αξία.")
        ordinary = []
        if any(has_role(item, "no_extra_cost") for item in chain.records):
            ordinary.append("Το επίσημο έγγραφο αναφέρει ότι δεν υπάρχει πρόσθετη οικονομική επιβάρυνση.")
        if any(has_role(item, "pending_replacement_tender") for item in chain.records):
            ordinary.append("Η παράταση συνδέεται ρητά με εκκρεμή νέα διαδικασία.")
        output.append(candidate(
            primary_type="advanced_or_repeated_extension",
            chain_ids={chain.chain_id},
            records=chain.records[:8],
            families=families,
            reasons=reasons,
            ordinary_explanations=ordinary,
            score_args={
                "evidence_quality": 26,
                "pattern_strength": 18 if max_rank >= 5 else 14,
                "peer_deviation": 0,
                "materiality": 5 if final_value else 2,
                "falsification_survival": max(2, 10 - 4 * len(ordinary)),
                "evidence_roles_complete": bool(amount_delta and final_value) if "financial_change" in families else True,
                "page_provenance": all(fact.source_page is not None for fact in change_facts),
                "strong_ordinary_explanation": bool(ordinary),
            },
            metrics={"max_modification_rank": max_rank, "modification_fact_count": len(change_facts)},
        ))

    unit_groups: dict[tuple[str, str, str, str], list[tuple[Chain, EvidenceRecord, Fact]]] = defaultdict(list)
    for chain in chains:
        record = chain.representative
        price_facts = [fact for fact in record.facts if fact.role == "explicit_unit_price" and fact.confidence >= 0.85 and fact.source_page is not None]
        for price_fact in price_facts:
            unit_groups[(record.category, price_fact.basis or "unspecified", price_fact.unit, infer_vat_basis(price_fact.source_excerpt))].append((chain, record, price_fact))
    for cohort_key, values in unit_groups.items():
        if len(values) < 4:
            continue
        for target_chain, target_record, target_fact in values:
            peers = [fact for chain, _, fact in values if chain.chain_id != target_chain.chain_id]
            if len(peers) < 3:
                continue
            peer_values = [float(fact.value) for fact in peers]
            median = statistics.median(peer_values)
            if median <= 0:
                continue
            ratio = float(target_fact.value) / median
            difference = float(target_fact.value) - median
            if ratio < 2.5 or difference < max(50, median * 0.75):
                continue
            families = {"unit_price_comparator"}
            if has_role(target_record, "single_bid"):
                families.add("competition")
            output.append(candidate(
                primary_type="strict_unit_price_outlier",
                chain_ids={target_chain.chain_id},
                records=[target_record],
                families=families,
                reasons=[f"Typed τιμή μονάδας €{float(target_fact.value):,.2f} έναντι leave-one-out διαμέσου €{median:,.2f} ({ratio:.2f}×).", f"Υπάρχουν {len(peers)} επίσημοι peers ίδιου category/spec/unit/VAT cohort."],
                ordinary_explanations=["Απαιτείται έλεγχος εγκατάστασης, μεταφοράς, εγγύησης, παρελκομένων και ακριβούς τεχνικού scope."],
                score_args={
                    "evidence_quality": 28,
                    "pattern_strength": 18,
                    "peer_deviation": min(20, 12 + int((ratio - 2.5) * 3)),
                    "materiality": 4,
                    "falsification_survival": 6,
                    "evidence_roles_complete": True,
                    "page_provenance": True,
                    "strong_ordinary_explanation": False,
                },
                metrics={"cohort": cohort_key, "peer_count": len(peers), "unit_price_eur": round(float(target_fact.value), 4), "peer_median_eur": round(median, 4), "ratio": round(ratio, 3)},
            ))

    return merge_case_candidates(output)


def merge_case_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for candidate_item in sorted(candidates, key=lambda item: (item["review_priority"], len(item["families"])), reverse=True):
        chain_ids = set(candidate_item["chain_ids"])
        match = None
        for current in merged:
            if chain_ids & set(current["chain_ids"]):
                match = current
                break
        if match is None:
            merged.append(candidate_item)
            continue
        match["detectors"] = sorted(set(match["detectors"]) | set(candidate_item["detectors"]))
        match["families"] = sorted(set(match["families"]) | set(candidate_item["families"]))
        match["chain_ids"] = sorted(set(match["chain_ids"]) | set(candidate_item["chain_ids"]))
        match["reasons"] = list(dict.fromkeys([*match["reasons"], *candidate_item["reasons"]]))
        match["ordinary_explanations"] = list(dict.fromkeys([*match["ordinary_explanations"], *candidate_item["ordinary_explanations"]]))
        if candidate_item["review_priority"] > match["review_priority"]:
            for key in ("review_priority", "score_axes", "caps", "primary_type", "status"):
                match[key] = candidate_item[key]
        existing_adas = {record["ada"] for record in match["records"]}
        match["records"].extend(record for record in candidate_item["records"] if record["ada"] not in existing_adas)
        match["case_fingerprint"] = hashlib.sha256("|".join(match["chain_ids"]).encode()).hexdigest()[:18]
        match["seen_in_previous_run"] = any(record["ada"] in PREVIOUS_ADAS for record in match["records"])
        match["novelty_rank_score"] = match["review_priority"] - (10 if match["seen_in_previous_run"] else 0)
    return sorted(merged, key=lambda item: (item["novelty_rank_score"], item["review_priority"], len(item["families"])), reverse=True)


def choose_diverse(candidates: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_primary_types: set[str] = set()
    for item in candidates:
        if item["primary_type"] in used_primary_types:
            continue
        selected.append(item)
        used_primary_types.add(item["primary_type"])
        if len(selected) >= limit:
            break
    return selected


def discovery_score(lane: str, subject: str) -> int:
    base = {"competition": 32, "procedure": 22, "emergency": 25, "timeline": 27, "modification": 18, "unit_price": 30}[lane]
    value = fold(subject)
    if any(term in value for term in ("5η τροποποιηση", "4η τροποποιηση", "μοναδικη προσφορα")):
        base += 6
    return base


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    session = requests.Session()
    session.headers.update({"User-Agent": "MizAI typed evidence-graph hunter v2/1.0", "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.1"})

    seeds: dict[str, Seed] = {}
    attempts: list[dict[str, Any]] = []
    for lane, terms in LANES.items():
        for term in terms:
            windows = list(YEAR_WINDOWS)
            rng.shuffle(windows)
            for start, end in windows:
                pages = list(dict.fromkeys([0, 1, rng.choice([2, 3, 4, 5])]))
                for page in pages:
                    response = request(session, SEARCH_URL, params={"term": term, "page": page, "size": PAGE_SIZE, "from_issue_date": start, "to_issue_date": end})
                    decisions = []
                    if response.ok:
                        payload = response.json()
                        decisions = payload.get("decisions") if isinstance(payload, dict) and isinstance(payload.get("decisions"), list) else []
                    attempts.append({"lane": lane, "term": term, "window": [start, end], "page": page, "status": response.status_code, "count": len(decisions)})
                    for raw in decisions:
                        if not isinstance(raw, dict):
                            continue
                        ada = str(raw.get("ada") or "").strip()
                        if not ada:
                            continue
                        subject = compact(raw.get("subject"), 600)
                        current = seeds.setdefault(ada, Seed(ada=ada))
                        current.lanes.add(lane)
                        if len(subject) > len(current.subject):
                            current.subject = subject
                        current.discovery_score = max(current.discovery_score, discovery_score(lane, subject))
                    if len(decisions) < PAGE_SIZE:
                        break
                    time.sleep(REQUEST_SLEEP)

    regression_seed = seeds.setdefault(TIMELINE_REGRESSION_ADA, Seed(ada=TIMELINE_REGRESSION_ADA, lanes={"regression_control"}, subject="", discovery_score=0))
    chosen: dict[str, Seed] = {}
    for lane in ("unit_price", "competition", "timeline", "procedure", "emergency", "modification"):
        pool = [seed for seed in seeds.values() if lane in seed.lanes]
        rng.shuffle(pool)
        pool.sort(key=lambda seed: (seed.discovery_score, len(seed.lanes)), reverse=True)
        for seed in pool[: LANE_QUOTAS[lane]]:
            chosen.setdefault(seed.ada, seed)
            if len(chosen) >= MAX_DEEP:
                break
        if len(chosen) >= MAX_DEEP:
            break
    chosen.setdefault(regression_seed.ada, regression_seed)

    inspected: list[EvidenceRecord] = []
    failures: list[dict[str, str]] = []
    for index, seed in enumerate(chosen.values(), start=1):
        try:
            record = inspect_decision(session, seed)
            if record is not None:
                inspected.append(record)
        except Exception as exc:
            failures.append({"ada": seed.ada, "error": type(exc).__name__, "message": str(exc)[:300]})
        if index % 10 == 0:
            print(f"inspected {index}/{len(chosen)}", flush=True)
        time.sleep(REQUEST_SLEEP)

    current = [record for record in inspected if record.current]
    chains = collapse_chains(current)
    candidates = build_candidates(chains)
    diverse = choose_diverse(candidates)

    all_facts = [fact for record in current for fact in record.facts]
    page_facts = [fact for fact in all_facts if fact.source_page is not None]
    typed_scoring_facts = [fact for fact in all_facts if fact.dependency_group not in {"audit", "context"}]
    regression_candidates = [item for item in candidates if any(record["ada"] == TIMELINE_REGRESSION_ADA for record in item["records"])]
    ekab_candidates = [item for item in candidates if {"ΨΔΘΔΟΡ1Π-Β28", "97ΤΖΟΡ1Π-Η0Θ", "Ρ6ΤΡΟΡ1Π-ΖΚΩ"} & {record["ada"] for record in item["records"]}]

    evaluation = {
        "timeline_false_positive_regression_passed": not any(item["primary_type"] == "typed_service_before_decision" for item in regression_candidates),
        "case_level_ekab_dedup_passed": len(ekab_candidates) <= 1,
        "page_provenance_ratio_all_facts": round(len(page_facts) / len(all_facts), 4) if all_facts else None,
        "typed_scoring_fact_count": len(typed_scoring_facts),
        "candidate_case_count_after_merge": len(candidates),
        "distinct_primary_patterns_in_diverse_top": len({item["primary_type"] for item in diverse}),
        "validated_80_plus_count": sum(item["status"] == "FOUND_VALIDATED" for item in candidates),
        "previously_seen_case_count_in_top": sum(item["seen_in_previous_run"] for item in diverse),
    }

    result = {
        "status": "completed" if inspected else "source_failure",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "coverage": {
            "metadata_records": len(seeds),
            "selected_for_pdf": len(chosen),
            "inspected": len(inspected),
            "current_decisions": len(current),
            "collapsed_chains": len(chains),
            "candidate_cases_after_merge": len(candidates),
            "failures": failures,
            "attempts": attempts,
        },
        "evaluation": evaluation,
        "diverse_top_results": diverse,
        "all_case_candidates": candidates[:60],
        "method_notes": [
            "Search terms are discovery-only and never become evidence.",
            "Dates and amounts need typed roles, scope, confidence, page and excerpt before scoring.",
            "ADAM/related-ADA links are provenance and never count as an independent evidence family.",
            "Detector results sharing a chain are merged into one case graph.",
            "The known school-maintenance timeline false positive is fetched only as a negative regression control.",
            "Cross-run novelty affects ranking, not the underlying review-priority score.",
            "Denominators computed from this sample are explicitly labelled discovery-biased.",
        ],
    }
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["rank\tstatus\tscore\tnovelty_rank\tprimary_type\tdetectors\tfamilies\tadas\treasons"]
    for index, item in enumerate(diverse, start=1):
        adas = ",".join(record["ada"] for record in item["records"])
        lines.append("\t".join([str(index), item["status"], str(item["review_priority"]), str(item["novelty_rank_score"]), item["primary_type"], ",".join(item["detectors"]), ",".join(item["families"]), adas, " | ".join(item["reasons"])]))
    (OUT / "diverse-results.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "evaluation.json").write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metadata_records": len(seeds), "inspected": len(inspected), "chains": len(chains), "case_candidates": len(candidates), "diverse_top": len(diverse), "evaluation": evaluation}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
