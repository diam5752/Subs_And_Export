#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import math
import random
import re
import shutil
import statistics
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from pypdf import PdfReader

SOURCE_URL = "https://raw.githubusercontent.com/troboukis/2026_fire_protection/main/data/2026_diavgeia.csv"
DETAIL_URL = "https://diavgeia.gov.gr/luminapi/api/decisions/{ada}"
PDF_URL = "https://diavgeia.gov.gr/doc/{ada}"
SEEDS = (5601, 5602)
MIN_SCORE = 80
MAX_DEEP_CHECKS_PER_RUN = 24
MAX_DOCS_PER_CANDIDATE = 10
MAX_PDF_BYTES = 14 * 1024 * 1024
USER_AGENT = "MizAI-Diavgeia-Blind-Validation/2.0 (+research; read-only)"

ADA_RE = re.compile(r"(?<![0-9A-ZΑ-Ω])([0-9A-ZΑ-Ω]{4,14}-[0-9A-ZΑ-Ω]{3})(?![0-9A-ZΑ-Ω])")
ADAM_RE = re.compile(r"\b((?:1[3-9]|2[0-9])(?:REQ|PROC|AWRD|SYMV|PAY)\d{9,12})\b", re.I)
ADAM_ROOT_RE = re.compile(r"^((?:1[3-9]|2[0-9]))(?:REQ|PROC|AWRD|SYMV|PAY)(\d{9,12})$", re.I)
CONTRACT_REF_RE = re.compile(
    r"(?:συμβασ(?:η|ης)|συμφωνητικ(?:ο|ου)|αρ\.?\s*πρωτ\.?)\D{0,35}(\d{1,7}\s*/\s*20\d{2})",
    re.I,
)
GEO_RE = re.compile(r"\b(?:δ\.?\s*ε\.?|δημοτικ(?:η|ης)\s+ενοτητα(?:ς)?)\s+([α-ωa-zάέήίόύώϊϋΐΰ\- ]{3,45})", re.I)

DIRECT_TERMS = (
    "απευθειας αναθεση", "απ ευθειας αναθεση", "αρθρο 118",
    "διαπραγματευση χωρις προηγουμενη δημοσιευση", "χωρις προηγουμενη δημοσιευση",
)
EMERGENCY_TERMS = (
    "κατεπειγον", "κατεπειγουσα", "εκτακτη αναγκη", "εξαιρετικα επειγον",
    "απροβλεπτ", "red code",
)
MODIFICATION_TERMS = (
    "τροποποιηση συμβασης", "τροποποιηση συμφωνητικ", "παραταση συμβασης",
    "παραταση συμφωνητικ", "συμπληρωματικη συμβαση", "συμπληρωμα νο",
    "ανακεφαλαιωτικ", "α π ε", "απε του εργου", "αυξηση οικονομικου αντικειμενου",
)
PAYMENT_TERMS = ("χρηματικο ενταλμα", "οριστικοποιηση πληρωμης", "εξοφληση", "πληρωμη")
COMMITMENT_TERMS = ("αναληψη υποχρεωσης", "δεσμευση πιστωσης")
AWARD_TERMS = ("απευθειας αναθεση", "αναθεση εργων", "κατακυρωση", "εγκριση αποτελεσματος")
CONTRACT_TERMS = ("συμβαση", "συμφωνητικ")
ROUTINE_EXCLUSIONS = (
    "μισθοδοσια", "υπερωρια", "εκτος εδρας", "μετακινηση υπαλληλ", "οδοιπορικα",
    "παγια προκαταβολη", "αποδοση κρατησεων", "φορος μισθωτων", "ασφαλιστικες εισφορες",
    "επιχορηγηση", "προυπολογισμου", "αναμορφωση προυπολογισμου", "μειωση μισθωματων",
)
ORDINARY_EXPLANATION_TERMS = (
    "αγονος διαγωνισμος", "αποβηκε αγονος", "προηγουμενη ανοικτη διαδικασια",
    "ανοιχτη διαδικασια", "προσφυγη", "αναστολη", "ακυρωση διαγωνισμου",
    "μονο ως προς τη διαρκεια", "δεν μεταβαλλεται το οικονομικο αντικειμενο",
    "χωρις αυξηση του οικονομικου αντικειμενου", "διασφαλιση της υγειας του ασθενους",
)
MEDICAL_URGENCY_TERMS = ("ασθεν", "χειρουργ", "φαρμακ", "κλινικη", "διασφαλιση της υγειας")
GENERIC_STOPWORDS = {
    "αποφαση", "εγκριση", "δαπανη", "δαπανης", "αναληψη", "υποχρεωσης", "αναθεση",
    "απευθειας", "συμβαση", "συμβασης", "συμφωνητικο", "συμφωνητικου", "προμηθεια",
    "προμηθειας", "παροχη", "υπηρεσια", "υπηρεσιων", "εργασια", "εργασιων", "εργο",
    "εργου", "για", "την", "των", "του", "της", "και", "με", "στο", "στη", "στις",
    "στους", "απο", "σε", "περι", "αρ", "αριθ", "ετους", "οικονομικου", "φορεα",
    "αναδοχου", "δημου", "δημος", "περιφερειας", "τροποποιηση", "παραταση",
    "συμπληρωματικη", "πρωτη", "δευτερη", "τριτη", "1η", "2η", "3η", "απε",
}


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("ς", "σ")
    text = re.sub(r"[^0-9a-zα-ω]+", " ", text)
    return " ".join(text.split())


def parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "null", "[]", "{}"}:
        return None
    text = re.sub(r"[^\d,.\- ]", "", text).replace(" ", "")
    if not text or text.startswith("-") or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = text.replace(".", "").replace(",", "." if len(parts[-1]) in {1, 2} else "")
    elif "." in text:
        parts = text.split(".")
        if (len(parts) > 2 and all(len(p) == 3 for p in parts[1:])) or (len(parts) > 1 and len(parts[-1]) == 3):
            text = text.replace(".", "")
    try:
        result = float(text)
    except ValueError:
        return None
    return round(result, 2) if math.isfinite(result) and result > 0 else None


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.casefold() in {"nan", "none", "null"}:
        return None
    for dayfirst in (True, False):
        try:
            return pd.to_datetime(text, dayfirst=dayfirst, errors="raise", utc=True).to_pydatetime().replace(tzinfo=None)
        except Exception:
            pass
    return None


def split_listish(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text.casefold() in {"nan", "none", "null", "[]", "{}"}:
        return []
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                parsed = list(parsed.values())
            if isinstance(parsed, (list, tuple, set)):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    return [part.strip(" []'\"") for part in re.split(r"[|;,]", text) if part.strip(" []'\"")]


def first_nonempty(row: pd.Series, keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value and value.casefold() not in {"nan", "none", "null", "[]", "{}"}:
            return value
    return ""


def first_amount(row: pd.Series, keys: Iterable[str]) -> float | None:
    for key in keys:
        value = parse_amount(row.get(key))
        if value is not None:
            return value
    return None


def afms(value: Any) -> list[str]:
    found: list[str] = []
    for item in split_listish(value) or [str(value or "")]:
        for token in re.findall(r"\d{8,10}", item):
            token = token[-9:]
            if token not in found:
                found.append(token)
    return found


def contains(text: str, terms: Iterable[str]) -> bool:
    return any(norm(term) in text for term in terms)


def topic_key(subject: str) -> str:
    tokens: list[str] = []
    for token in norm(subject).split():
        if token in GENERIC_STOPWORDS or token.isdigit() or len(token) < 4:
            continue
        if re.fullmatch(r"\d+[a-zα-ω]*", token):
            continue
        stem = token[:8]
        if stem not in tokens:
            tokens.append(stem)
    return " ".join(sorted(tokens[:5])) or norm(subject)[:80]


def geography(subject: str) -> str:
    match = GEO_RE.search(norm(subject))
    if not match:
        return "unspecified"
    value = norm(match.group(1))
    value = re.split(r"\b(?:του|της|για|βασει|ετους|δημου|στο|στη)\b", value)[0].strip()
    return " ".join(value.split()[:5]) or "unspecified"


def adam_roots(text: str) -> set[str]:
    roots: set[str] = set()
    for adam in ADAM_RE.findall(text.upper()):
        match = ADAM_ROOT_RE.match(adam)
        if match:
            roots.add(f"ADAMROOT:{match.group(1)}:{match.group(2)}")
    return roots


def contract_refs(text: str) -> set[str]:
    return {f"CONTRACT:{re.sub(r'\s+', '', value)}" for value in CONTRACT_REF_RE.findall(norm(text))}


def ada_refs(text: str) -> set[str]:
    return set(ADA_RE.findall(text.upper()))


def jaccard(left: str, right: str) -> float:
    a, b = set(norm(left).split()), set(norm(right).split())
    return len(a & b) / len(a | b) if a and b else 0.0


def stage_for(text: str, decision_type: str) -> str:
    hay = norm(f"{decision_type} {text}")
    if contains(hay, PAYMENT_TERMS):
        return "payment"
    if contains(hay, COMMITMENT_TERMS):
        return "commitment"
    if contains(hay, AWARD_TERMS):
        return "award"
    if contains(hay, CONTRACT_TERMS):
        return "contract"
    return "other"


@dataclass
class Rec:
    ada: str
    subject: str
    organization: str
    decision_type: str
    stage: str
    amount: float | None
    supplier_afm: str
    supplier_name: str
    observed_at: datetime
    year: int
    geo: str
    topic: str
    raw_text: str
    direct: bool
    emergency: bool
    modification: bool
    roots: set[str] = field(default_factory=set)
    refs: set[str] = field(default_factory=set)
    live_text: str = ""
    official_url: str = ""

    def combined_text(self) -> str:
        return " ".join((self.raw_text, self.live_text))

    def refreshed_roots(self) -> set[str]:
        text = self.combined_text()
        return {*self.roots, *adam_roots(text), *contract_refs(text)}


class DSU:
    def __init__(self, values: Iterable[str]):
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


def normalize_records(frame: pd.DataFrame) -> list[Rec]:
    records: list[Rec] = []
    for _, row in frame.iterrows():
        ada = str(row.get("ada", "") or "").strip()
        subject = str(row.get("subject", "") or "").strip()
        organization = first_nonempty(row, ("org_name_clean", "org", "organization"))
        decision_type = first_nonempty(row, ("decisionType", "documentType"))
        observed = parse_dt(row.get("issueDate")) or parse_dt(row.get("publishTimestamp")) or parse_dt(row.get("submissionTimestamp"))
        if not ada or not subject or not organization or observed is None:
            continue
        raw = " ".join(
            str(row.get(key, "") or "")
            for key in (
                "subject", "pdf_text", "direct_related_commitment", "direct_see_also",
                "payment_related_commitment_or_spending", "payment_see_also", "protocolNumber",
            )
        )
        normalized = norm(raw)
        if contains(normalized, ROUTINE_EXCLUSIONS):
            continue
        amount = first_amount(
            row,
            (
                "payment_value", "direct_value", "spending_contractors_value",
                "commitment_amount_with_vat",
            ),
        )
        supplier_ids = afms(first_nonempty(row, ("payment_beneficiary_afm", "direct_afm", "spending_contractors_afm")))
        supplier_name = first_nonempty(row, ("payment_beneficiary_name", "direct_name", "spending_contractors_name"))
        records.append(
            Rec(
                ada=ada,
                subject=subject,
                organization=organization,
                decision_type=decision_type,
                stage=stage_for(raw, decision_type),
                amount=amount,
                supplier_afm=supplier_ids[0] if supplier_ids else "",
                supplier_name=supplier_name,
                observed_at=observed,
                year=observed.year,
                geo=geography(subject),
                topic=topic_key(subject),
                raw_text=raw,
                direct=contains(normalized, DIRECT_TERMS),
                emergency=contains(normalized, EMERGENCY_TERMS),
                modification=contains(normalized, MODIFICATION_TERMS),
                roots={*adam_roots(raw), *contract_refs(raw)},
                refs=ada_refs(raw) - {ada},
                official_url=f"https://diavgeia.gov.gr/doc/{ada}",
            )
        )
    dedup: dict[str, Rec] = {}
    for rec in records:
        dedup.setdefault(rec.ada, rec)
    return list(dedup.values())


def chain_map(records: list[Rec]) -> dict[str, str]:
    by_ada = {rec.ada: rec for rec in records}
    dsu = DSU(by_ada)
    root_owner: dict[str, str] = {}
    exact_owner: dict[tuple[Any, ...], str] = {}
    for rec in records:
        for ref in rec.refs:
            if ref in by_ada:
                dsu.union(rec.ada, ref)
        for root in rec.refreshed_roots():
            if root in root_owner:
                dsu.union(rec.ada, root_owner[root])
            else:
                root_owner[root] = rec.ada
        exact_key = (
            norm(rec.organization), rec.year, rec.geo, norm(rec.subject), rec.amount,
            rec.observed_at.date().isoformat(), rec.stage,
        )
        if exact_key in exact_owner:
            dsu.union(rec.ada, exact_owner[exact_key])
        else:
            exact_owner[exact_key] = rec.ada
    return {ada: dsu.find(ada) for ada in by_ada}


def chain_representatives(records: list[Rec]) -> list[dict[str, Any]]:
    mapping = chain_map(records)
    grouped: dict[str, list[Rec]] = defaultdict(list)
    for rec in records:
        grouped[mapping[rec.ada]].append(rec)
    chains: list[dict[str, Any]] = []
    for key, docs in grouped.items():
        nonpayments = [doc.amount for doc in docs if doc.stage != "payment" and doc.amount is not None]
        all_amounts = [doc.amount for doc in docs if doc.amount is not None]
        chains.append(
            {
                "key": key,
                "docs": docs,
                "amount": max(nonpayments or all_amounts) if (nonpayments or all_amounts) else None,
                "direct": any(doc.direct for doc in docs),
                "emergency": any(doc.emergency for doc in docs),
                "modification": any(doc.modification for doc in docs),
                "suppliers": {doc.supplier_afm for doc in docs if doc.supplier_afm},
                "date": min(doc.observed_at for doc in docs),
                "subject": max((doc.subject for doc in docs), key=len),
            }
        )
    return chains


def band_for(amount: float) -> float | None:
    for band in (30000.0, 60000.0):
        if 0.82 * band <= amount <= band:
            return band
    return None


def group_score(records: list[Rec], kind: str) -> tuple[int, dict[str, int], list[str], dict[str, Any]]:
    chains = chain_representatives(records)
    if len(chains) < 3:
        return 0, {}, [], {"distinct_chains": len(chains)}
    families: dict[str, int] = {}
    facts: list[str] = []
    direct_count = sum(1 for chain in chains if chain["direct"])
    emergency_count = sum(1 for chain in chains if chain["emergency"])
    if direct_count >= 3:
        families["repeated_procedure_choice"] = 22
        facts.append(f"{direct_count} διακριτές αλυσίδες πράξεων αναφέρουν ρητά απευθείας ανάθεση ή ισοδύναμη διαδικασία.")
    if emergency_count >= 3:
        families["repeated_emergency_pattern"] = 22
        facts.append(f"{emergency_count} διακριτές αλυσίδες επικαλούνται επείγον ή έκτακτη ανάγκη.")
    by_band: dict[float, list[float]] = defaultdict(list)
    for chain in chains:
        amount = chain["amount"]
        if amount is not None and (band := band_for(amount)) is not None:
            by_band[band].append(amount)
    for band, values in by_band.items():
        if len(values) >= 3 and sum(values) >= 1.5 * band:
            families["cumulative_near_band_pattern"] = 28
            facts.append(
                f"{len(values)} διακριτές αλυσίδες έχουν ποσά κοντά στο εσωτερικό review band €{band:,.0f}, με άθροισμα €{sum(values):,.2f}."
            )
            break
    span_days = (max(chain["date"] for chain in chains) - min(chain["date"] for chain in chains)).days
    pair_scores = [
        jaccard(left["subject"], right["subject"])
        for index, left in enumerate(chains)
        for right in chains[index + 1 :]
    ]
    median_similarity = statistics.median(pair_scores) if pair_scores else 0.0
    distinct_amounts = {chain["amount"] for chain in chains if chain["amount"] is not None}
    distinct_suppliers = set().union(*(chain["suppliers"] for chain in chains))
    if len(chains) >= 4 and span_days <= 45 and median_similarity >= 0.82 and (len(distinct_amounts) >= 2 or len(distinct_suppliers) >= 2):
        families["duplicate_or_template_burst"] = 20
        facts.append(
            f"{len(chains)} διακριτές αλυσίδες σε {span_days} ημέρες έχουν υψηλή ομοιότητα τίτλων (διάμεση Jaccard {median_similarity:.2f})."
        )
    supplier_counts: dict[str, int] = defaultdict(int)
    supplier_totals: dict[str, float] = defaultdict(float)
    for chain in chains:
        for supplier in chain["suppliers"]:
            supplier_counts[supplier] += 1
            supplier_totals[supplier] += chain["amount"] or 0.0
    if supplier_counts:
        supplier, count = max(supplier_counts.items(), key=lambda item: (item[1], supplier_totals[item[0]]))
        if count >= 3 and supplier_totals[supplier] >= 30000:
            families["supplier_object_pattern"] = 28
            facts.append(
                f"Το ίδιο ΑΦΜ εμφανίζεται σε {count} διακριτές αλυσίδες του ίδιου φορέα/αντικειμένου, συνολικού ποσού €{supplier_totals[supplier]:,.2f}."
            )
    if len(families) < 2:
        return 0, families, facts, {"distinct_chains": len(chains)}
    score = min(94, 30 + sum(families.values()))
    return score, families, facts, {
        "distinct_chains": len(chains),
        "span_days": span_days,
        "median_similarity": round(median_similarity, 3),
        "kind": kind,
    }


def chain_score(records: list[Rec]) -> tuple[int, dict[str, int], list[str], dict[str, Any]]:
    chains = chain_representatives(records)
    if len(chains) != 1:
        return 0, {}, [], {"distinct_chains": len(chains)}
    docs = chains[0]["docs"]
    families: dict[str, int] = {}
    facts: list[str] = []
    reference_amounts = [doc.amount for doc in docs if doc.stage in {"award", "contract", "commitment"} and doc.amount is not None]
    payment_events: dict[tuple[Any, ...], float] = {}
    for doc in docs:
        if doc.stage != "payment" or doc.amount is None:
            continue
        key = (doc.amount, doc.supplier_afm, doc.observed_at.date().isoformat(), norm(doc.subject))
        payment_events[key] = doc.amount
    if reference_amounts and payment_events:
        reference = max(reference_amounts)
        payment_total = sum(payment_events.values())
        ratio = payment_total / reference if reference else 0.0
        gap = payment_total - reference
        if ratio >= 1.05 and gap >= 1000:
            families["linked_financial_consistency"] = 32
            facts.append(
                f"Στην ίδια ρητά συνδεδεμένη αλυσίδα οι μοναδικές πληρωμές είναι €{payment_total:,.2f} έναντι ποσού αναφοράς €{reference:,.2f} ({ratio:.2f}×)."
            )
    modification_docs = [doc for doc in docs if doc.modification]
    distinct_mod_amounts = {doc.amount for doc in modification_docs if doc.amount is not None}
    if len(modification_docs) >= 2 and (len(distinct_mod_amounts) >= 2 or len(modification_docs) >= 3):
        families["cumulative_modification_sequence"] = 26
        facts.append(f"Η ίδια αλυσίδα περιέχει {len(modification_docs)} διακριτά έγγραφα τροποποίησης/παράτασης.")
    lags = []
    for doc in docs:
        detail_date = parse_dt(doc.observed_at)
        if detail_date:
            lags.append(0)
    if len(families) < 2:
        return 0, families, facts, {"distinct_chains": 1}
    return min(96, 30 + sum(families.values())), families, facts, {"distinct_chains": 1}


@dataclass
class Candidate:
    key: str
    kind: str
    records: list[Rec]
    score: int
    families: dict[str, int]
    facts: list[str]
    diagnostics: dict[str, Any]

    def ada_set(self) -> set[str]:
        return {record.ada for record in self.records}


def build_candidates(records: list[Rec]) -> list[Candidate]:
    candidates: list[Candidate] = []
    grouped: dict[tuple[str, int, str, str], list[Rec]] = defaultdict(list)
    supplier_grouped: dict[tuple[str, str, int, str, str], list[Rec]] = defaultdict(list)
    for rec in records:
        base_key = (norm(rec.organization), rec.year, rec.geo, rec.topic)
        grouped[base_key].append(rec)
        if rec.supplier_afm:
            supplier_grouped[(norm(rec.organization), rec.supplier_afm, rec.year, rec.geo, rec.topic)].append(rec)
    for key, docs in grouped.items():
        score, families, facts, diag = group_score(docs, "authority_topic_year_geo")
        if score:
            candidates.append(Candidate(f"GROUP:{key}", "group", docs, score, families, facts, diag))
    for key, docs in supplier_grouped.items():
        score, families, facts, diag = group_score(docs, "authority_supplier_topic_year_geo")
        if score:
            candidates.append(Candidate(f"SUPPLIER:{key}", "group", docs, score, families, facts, diag))
    mapping = chain_map(records)
    chain_docs: dict[str, list[Rec]] = defaultdict(list)
    for rec in records:
        chain_docs[mapping[rec.ada]].append(rec)
    for key, docs in chain_docs.items():
        score, families, facts, diag = chain_score(docs)
        if score:
            candidates.append(Candidate(f"CHAIN:{key}", "chain", docs, score, families, facts, diag))
    unique: dict[frozenset[str], Candidate] = {}
    for candidate in candidates:
        adas = frozenset(candidate.ada_set())
        existing = unique.get(adas)
        if existing is None or candidate.score > existing.score:
            unique[adas] = candidate
    return sorted(unique.values(), key=lambda candidate: (-candidate.score, candidate.key))


def fetch_json(session: requests.Session, url: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = session.get(url, timeout=(10, 35), headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        return (payload, None) if isinstance(payload, dict) else (None, "non_object_json")
    except Exception as exc:
        return None, f"{type(exc).__name__}:{exc}"


def current_detail(payload: dict[str, Any]) -> bool:
    status = norm(payload.get("status"))
    return (
        status in {"published", "αναρτημενη", "αναρτημενη αποφαση"}
        and not payload.get("correctedVersionId")
        and payload.get("privateData") is not True
    )


def fetch_pdf_text(session: requests.Session, ada: str) -> tuple[str, str | None]:
    try:
        response = session.get(PDF_URL.format(ada=ada), timeout=(10, 45), stream=True)
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > MAX_PDF_BYTES:
                return "", "pdf_too_large"
        reader = PdfReader(io.BytesIO(bytes(content)))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return text[:500000], None
    except Exception as exc:
        return "", f"{type(exc).__name__}:{exc}"


def detail_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def reevaluate(candidate: Candidate, valid_records: list[Rec]) -> tuple[int, dict[str, int], list[str], dict[str, Any]]:
    if candidate.kind == "chain":
        return chain_score(valid_records)
    return group_score(valid_records, candidate.diagnostics.get("kind", "group"))


def deep_validate(candidate: Candidate, session: requests.Session) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    ordered = sorted(candidate.records, key=lambda rec: (rec.observed_at, rec.ada))[:MAX_DOCS_PER_CANDIDATE]
    valid: list[Rec] = []
    detail_errors: dict[str, str] = {}
    pdf_errors: dict[str, str] = {}
    pdf_text_count = 0
    ordinary_terms: set[str] = set()
    for rec in ordered:
        payload, error = fetch_json(session, DETAIL_URL.format(ada=rec.ada))
        if error or payload is None:
            detail_errors[rec.ada] = error or "detail_missing"
            continue
        if not current_detail(payload):
            detail_errors[rec.ada] = "corrected_or_private_or_stale"
            continue
        pdf_text, pdf_error = fetch_pdf_text(session, rec.ada)
        if pdf_error:
            pdf_errors[rec.ada] = pdf_error
        else:
            pdf_text_count += 1
        rec.live_text = f"{detail_text(payload)}\n{pdf_text}"
        normalized_live = norm(rec.live_text)
        for term in ORDINARY_EXPLANATION_TERMS:
            if norm(term) in normalized_live:
                ordinary_terms.add(term)
        valid.append(rec)
    if len(valid) < 3 or pdf_text_count < 2:
        return None, {
            "reason": "insufficient_current_official_documents_or_pdf_text",
            "valid_documents": len(valid), "pdf_text_count": pdf_text_count,
            "detail_errors": detail_errors, "pdf_errors": pdf_errors,
        }
    score, families, facts, diagnostics = reevaluate(candidate, valid)
    if len(families) < 2 or score < MIN_SCORE:
        return None, {
            "reason": "collapsed_below_gate_after_live_chain_rebuild",
            "score": score, "families": families, "facts": facts,
            "diagnostics": diagnostics, "detail_errors": detail_errors,
        }
    combined = norm(" ".join(rec.live_text for rec in valid))
    medical_urgency = contains(combined, MEDICAL_URGENCY_TERMS)
    hard_family = "linked_financial_consistency" in families
    caps: list[str] = []
    if ordinary_terms and not hard_family:
        score = min(score, 69)
        caps.append("documented_ordinary_explanation_without_independent_hard_contradiction")
    if medical_urgency and not hard_family:
        score = min(score, 59)
        caps.append("documented_medical_urgency")
    if score < MIN_SCORE:
        return None, {
            "reason": "ordinary_explanation_cap",
            "score": score, "families": families, "ordinary_terms": sorted(ordinary_terms),
            "caps": caps,
        }
    docs = [
        {
            "ada": rec.ada,
            "subject": rec.subject,
            "organization": rec.organization,
            "decision_type": rec.decision_type,
            "stage": rec.stage,
            "amount_eur": rec.amount,
            "supplier_name": rec.supplier_name,
            "supplier_afm_redacted": ("******" + rec.supplier_afm[-3:]) if rec.supplier_afm else "",
            "observed_at": rec.observed_at.isoformat(),
            "official_url": rec.official_url,
        }
        for rec in valid
    ]
    result = {
        "review_priority": score,
        "score_meaning": "human_review_priority_not_probability_of_wrongdoing",
        "families": families,
        "evidence_facts": facts,
        "strongest_ordinary_explanation": (
            "Οι πράξεις μπορεί να είναι νόμιμες, διακριτές ανάγκες ή διαφορετικά στάδια· "
            "ο έλεγχος αναζήτησε ρητή τεκμηρίωση αυτής της εξήγησης στα διαθέσιμα επίσημα PDF."
        ),
        "validation": {
            "official_detail_current_count": len(valid),
            "official_detail_checked_count": len(ordered),
            "official_detail_errors": detail_errors,
            "pdf_text_count": pdf_text_count,
            "pdf_checked_count": len(valid),
            "pdf_errors": pdf_errors,
            "ordinary_explanation_terms_found": sorted(ordinary_terms),
            "validation_caps": caps,
            "evidence_complete_for_prioritisation": True,
            "distinct_chains_after_live_rebuild": diagnostics.get("distinct_chains"),
        },
        "candidate_source": candidate.diagnostics.get("kind", candidate.kind),
        "documents": docs,
    }
    return result, {"reason": "passed"}


def run_scans(records: list[Rec], candidates: list[Candidate]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    selected: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    used_adas: set[str] = set()
    eligible = [candidate for candidate in candidates if candidate.score >= MIN_SCORE and len(candidate.families) >= 2]
    for run_number, seed in enumerate(SEEDS, start=1):
        shuffled = eligible.copy()
        random.Random(seed).shuffle(shuffled)
        rejected: list[dict[str, Any]] = []
        chosen: dict[str, Any] | None = None
        checked = 0
        for candidate in shuffled:
            if candidate.ada_set() & used_adas:
                continue
            checked += 1
            result, reason = deep_validate(candidate, session)
            if result is not None:
                result.update({"run": run_number, "seed": seed})
                chosen = result
                selected.append(result)
                used_adas.update(candidate.ada_set())
                break
            rejected.append({"candidate": candidate.key, "pre_score": candidate.score, **reason})
            if checked >= MAX_DEEP_CHECKS_PER_RUN:
                break
        diagnostics.append(
            {
                "run": run_number,
                "seed": seed,
                "pre_gate_candidates": len(eligible),
                "deep_checked": checked,
                "rejected": rejected,
                "status": "FOUND" if chosen else "NO_QUALIFYING_CASE_WITHIN_SEARCH_BUDGET",
                "selected_adas": [doc["ada"] for doc in chosen["documents"]] if chosen else [],
                "selected_review_priority": chosen["review_priority"] if chosen else None,
            }
        )
    return selected, diagnostics


def write_outputs(out_dir: Path, *, source_hash: str, source_size: int, rows: int, records: list[Rec], candidates: list[Candidate], selected: list[dict[str, Any]], diagnostics: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "COMPLETED",
        "executed_at_utc": datetime.utcnow().isoformat() + "Z",
        "source": {
            "kind": "temporary_frozen_mirror_of_official_diavgeia_records",
            "url": SOURCE_URL,
            "sha256": source_hash,
            "bytes": source_size,
            "rows": rows,
            "scope": "available 2026 snapshot",
        },
        "method": {
            "runs": 2,
            "seeds": list(SEEDS),
            "minimum_review_priority": MIN_SCORE,
            "stop_each_run_at_first_passing_candidate": True,
            "persistent_raw_storage": False,
            "uses_outcome_labels_news_or_EAD": False,
            "score_is_probability_of_wrongdoing": False,
            "chain_guards": [
                "collapse_shared_ADAM_and_explicit_ADA_references",
                "collapse_exact_same_day_same_amount_same_subject_events",
                "partition_by_fiscal_year",
                "partition_by_municipal_unit_or_geography",
                "recompute_after_live_PDF_and_detail_references",
            ],
        },
        "coverage": {
            "normalized_unique_decisions": len(records),
            "generated_candidate_clusters": len(candidates),
            "pre_gate_80_or_more": sum(1 for candidate in candidates if candidate.score >= MIN_SCORE),
            "selected_count": len(selected),
        },
        "selected": selected,
        "run_diagnostics": diagnostics,
    }
    (out_dir / "scan_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "source_sha256": source_hash,
        "source_size": source_size,
        "rows": rows,
        "normalized_records": len(records),
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "raw_deleted_after_scan": True,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Diavgeia-only blind scan v4", "",
        f"- Raw rows: **{rows}**", f"- Normalized decisions: **{len(records)}**",
        f"- Candidate clusters: **{len(candidates)}**", f"- Results ≥80: **{len(selected)}**", "",
        "> Scores are human-review priorities, not probabilities of wrongdoing.", "",
    ]
    for item in selected:
        lines.extend([
            f"## Run {item['run']} — priority {item['review_priority']}/100", "",
            *[f"- {fact}" for fact in item["evidence_facts"]], "",
            *[f"- [{doc['ada']}]({doc['official_url']}) — {doc['subject']}" for doc in item["documents"]], "",
        ])
    if len(selected) < 2:
        lines.extend(["## Honest outcome", "", "The strict mechanism did not produce two independently validated results within this search budget."])
    (out_dir / "scan_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="scan-output")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    with tempfile.TemporaryDirectory(prefix="diavgeia-blind-") as tmp:
        raw_path = Path(tmp) / "diavgeia.csv"
        response = requests.get(SOURCE_URL, timeout=(15, 180), headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        raw_path.write_bytes(response.content)
        source_hash = hashlib.sha256(response.content).hexdigest()
        frame = pd.read_csv(raw_path, dtype=str, low_memory=False)
        records = normalize_records(frame)
        candidates = build_candidates(records)
        selected, diagnostics = run_scans(records, candidates)
        write_outputs(
            out_dir,
            source_hash=source_hash,
            source_size=len(response.content),
            rows=len(frame),
            records=records,
            candidates=candidates,
            selected=selected,
            diagnostics=diagnostics,
        )
        del frame
        raw_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
