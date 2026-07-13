#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
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
from urllib.parse import quote

import pandas as pd
import requests
from pypdf import PdfReader

SOURCE_URL = "https://raw.githubusercontent.com/troboukis/2026_fire_protection/main/data/2026_diavgeia.csv"
DETAIL_URL = "https://diavgeia.gov.gr/luminapi/api/decisions/{ada}"
PDF_URL = "https://diavgeia.gov.gr/doc/{ada}"
SEEDS = (5601, 5602)
MIN_SCORE = 80
MAX_DETAIL_DOCS = 8
MAX_PDF_DOCS = 4
MAX_PDF_BYTES = 12 * 1024 * 1024
USER_AGENT = "MizAI-Diavgeia-Blind-Validation/1.0"

ADA_RE = re.compile(r"(?<![0-9A-ZΑ-Ω])([0-9A-ZΑ-Ω]{4,12}-[0-9A-ZΑ-Ω]{3})(?![0-9A-ZΑ-Ω])")
ADAM_RE = re.compile(r"\b(?:1[3-9]|2[0-9])(?:REQ|PROC|AWRD|SYMV|PAY)\d{9,12}\b", re.I)

DIRECT_TERMS = (
    "απευθειασ αναθεση", "απ ευθειασ αναθεση", "αρθρο 118",
    "διαπραγματευση χωρισ προηγουμενη δημοσιευση", "χωρισ προηγουμενη δημοσιευση",
)
EMERGENCY_TERMS = (
    "κατεπειγον", "κατεπειγουσα", "εκτακτη αναγκη", "εξαιρετικα επειγον",
    "απροβλεπτ", "red code",
)
MODIFICATION_TERMS = (
    "τροποποιηση συμβασησ", "τροποποιηση συμφωνητικ", "παραταση συμβασησ",
    "παραταση συμφωνητικ", "συμπληρωματικη συμβαση", "συμπληρωμα νο",
    "ανακεφαλαιωτικ", "α π ε", "απε του εργου", "αυξηση οικονομικου αντικειμενου",
)
PAYMENT_TERMS = ("χρηματικο ενταλμα", "οριστικοποιηση πληρωμησ", "εξοφληση", "πληρωμη")
AWARD_TERMS = ("αναθεση", "κατακυρωση", "εγκριση αποτελεσμαοσ")
CONTRACT_TERMS = ("συμβαση", "συμφωνητικ")
ROUTINE_TERMS = (
    "μισθοδοσια", "υπερωρια", "εκτοσ εδρασ", "μετακινηση υπαλληλ", "οδοιπορικα",
    "παγια προκαταβολη", "αποδοση κρατησεων", "φοροσ μισθωτων",
    "ασφαλιστικεσ εισφορεσ", "επιχορηγηση", "αναμορφωση προυπολογισμου",
    "μειωση μισθωματων", "δημοτικα τελη",
)
MEDICAL_TERMS = ("ασθεν", "χειρουργ", "φαρμακ", "υγεια του ασθεν", "κλινικη")
ORDINARY_TERMS = (
    "αγονοσ διαγωνισμοσ", "αποβηκε αγονοσ", "προηγουμενη ανοικτη διαδικασια",
    "ανοιχτη διαδικασια", "προσφυγη", "αναστολη", "ακυρωση διαγωνισμου",
    "προσωρινη", "διασφαλιση τησ υγειασ", "λογοι ασφαλειασ",
    "μονο ωσ προσ τη διαρκεια", "δεν μεταβαλλεται το οικονομικο αντικειμενο",
)
STOPWORDS = {
    "αποφαση", "εγκριση", "δαπανη", "δαπανησ", "αναληψη", "υποχρεωσησ",
    "αναθεση", "απευθειασ", "συμβαση", "συμβασησ", "συμφωνητικο", "συμφωνητικου",
    "προμηθεια", "προμηθειασ", "παροχη", "υπηρεσια", "υπηρεσιων", "εργασια",
    "εργασιων", "εργο", "εργου", "για", "την", "των", "του", "τησ", "και", "με",
    "στο", "στη", "στισ", "στουσ", "απο", "σε", "περι", "αρ", "αριθ", "ετουσ",
    "οικονομικου", "φορεα", "αναδοχου", "δημου", "δημοσ", "περιφερειασ",
    "τροποποιηση", "παραταση", "συμπληρωματικη", "πρωτη", "δευτερη", "τριτη",
    "1η", "2η", "3η", "απε", "α", "π", "ε",
}


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("ς", "σ")
    text = re.sub(r"[^0-9a-zα-ω]+", " ", text)
    return " ".join(text.split())


def has(text: str, terms: Iterable[str]) -> bool:
    return any(norm(term) in text for term in terms)


def parse_amount(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.casefold() in {"nan", "none", "null", "[]", "{}"}:
        return None
    text = text.replace("\u00a0", " ").replace("€", "")
    text = re.sub(r"[^\d,.-]", "", text)
    if not text or text.startswith("-") or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = text.replace(".", "").replace(",", "." if len(parts[-1]) in {1, 2} else "")
    elif "." in text:
        parts = text.split(".")
        if len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
            text = text.replace(".", "")
        elif len(parts[-1]) == 3 and len(parts) > 1:
            text = text.replace(".", "")
    try:
        amount = float(text)
    except ValueError:
        return None
    return round(amount, 2) if math.isfinite(amount) and amount > 0 else None


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.casefold() in {"nan", "none", "null"}:
        return None
    for dayfirst in (True, False):
        try:
            parsed = pd.to_datetime(text, dayfirst=dayfirst, errors="raise", utc=True)
            return parsed.to_pydatetime().replace(tzinfo=None)
        except Exception:
            pass
    return None


def splitish(value: Any) -> list[str]:
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


def first_text(row: pd.Series, keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value and value.casefold() not in {"nan", "none", "null", "[]", "{}"}:
            return value
    return ""


def first_amount(row: pd.Series, keys: Iterable[str]) -> float | None:
    for key in keys:
        amount = parse_amount(row.get(key))
        if amount is not None:
            return amount
    return None


def afms(value: Any) -> list[str]:
    found: list[str] = []
    for item in splitish(value) or [str(value or "")]:
        for digits in re.findall(r"\d{8,10}", item):
            digits = digits[-9:]
            if digits not in found:
                found.append(digits)
    return found


def tokens(subject: str) -> set[str]:
    result = set()
    for token in norm(subject).split():
        if token in STOPWORDS or len(token) < 4 or token.isdigit():
            continue
        if re.fullmatch(r"\d+[a-zα-ω]*", token):
            continue
        result.add(token)
    return result


def topic_key(subject: str) -> str:
    meaningful = sorted(tokens(subject))
    return " ".join(meaningful[:3]) if meaningful else norm(subject)[:60]


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def refs(*values: Any) -> tuple[set[str], set[str]]:
    text = unicodedata.normalize("NFKC", " ".join(str(value or "") for value in values)).upper()
    return ({match.group(1) for match in ADA_RE.finditer(text)}, {match.group(0).upper() for match in ADAM_RE.finditer(text)})


def redact_afm(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return "******" + digits[-3:] if len(digits) >= 4 else ""


@dataclass
class Record:
    ada: str
    subject: str
    subject_n: str
    org: str
    org_n: str
    decision_type: str
    stage: str
    amount: float | None
    supplier_afm: str
    supplier_name: str
    observed: datetime | None
    published: datetime | None
    direct: bool
    emergency: bool
    modification: bool
    routine: bool
    medical: bool
    token_set: set[str]
    topic: str
    related_adas: set[str]
    related_adams: set[str]
    pdf_text: str
    url: str

    def public(self) -> dict[str, Any]:
        return {
            "ada": self.ada,
            "subject": self.subject,
            "organization": self.org,
            "decision_type": self.decision_type,
            "stage": self.stage,
            "amount_eur": self.amount,
            "supplier_name": self.supplier_name,
            "supplier_afm_redacted": redact_afm(self.supplier_afm),
            "observed_at": self.observed.isoformat() if self.observed else None,
            "official_url": self.url or PDF_URL.format(ada=quote(self.ada, safe="-")),
        }


@dataclass
class Candidate:
    indexes: tuple[int, ...]
    source: str
    pre_score: int = 0
    final_score: int = 0
    families: dict[str, int] = field(default_factory=dict)
    facts: list[str] = field(default_factory=list)
    caps: list[str] = field(default_factory=list)
    explanation: str = ""
    validation: dict[str, Any] = field(default_factory=dict)


def stage(row: pd.Series, subject_n: str, decision_n: str) -> str:
    if first_text(row, ["payment_value", "payment_beneficiary_afm"]):
        return "payment"
    if first_text(row, ["direct_value", "direct_afm"]):
        return "award"
    if has(subject_n, PAYMENT_TERMS) or "οριστικοποιηση πληρωμησ" in decision_n:
        return "payment"
    if has(subject_n, MODIFICATION_TERMS):
        return "modification"
    if has(subject_n, CONTRACT_TERMS):
        return "contract"
    if has(subject_n, AWARD_TERMS) or "αναθεση" in decision_n:
        return "award"
    if first_text(row, ["commitment_amount_with_vat", "commitment_kae_ale_number"]):
        return "commitment"
    if first_text(row, ["spending_contractors_value", "spending_contractors_afm"]):
        return "payment"
    return "other"


def build_records(frame: pd.DataFrame) -> list[Record]:
    selected: dict[str, Record] = {}
    for _, row in frame.iterrows():
        ada = str(row.get("ada", "") or "").strip()
        if not ada:
            continue
        status = norm(row.get("status", ""))
        if status and status != "published":
            continue
        subject = str(row.get("subject", "") or "").strip()
        subject_n = norm(subject)
        decision_type = str(row.get("decisionType", "") or "").strip()
        decision_n = norm(decision_type)
        stg = stage(row, subject_n, decision_n)
        amount_fields = {
            "award": ["direct_value", "spending_contractors_value", "commitment_amount_with_vat"],
            "payment": ["payment_value", "spending_contractors_value", "direct_value", "commitment_amount_with_vat"],
            "commitment": ["commitment_amount_with_vat", "direct_value", "spending_contractors_value"],
            "contract": ["direct_value", "spending_contractors_value", "commitment_amount_with_vat"],
            "modification": ["direct_value", "spending_contractors_value", "commitment_amount_with_vat", "payment_value"],
        }.get(stg, ["direct_value", "payment_value", "spending_contractors_value", "commitment_amount_with_vat"])
        amount = first_amount(row, amount_fields)
        supplier_afm = ""
        for field_name in ("direct_afm", "payment_beneficiary_afm", "spending_contractors_afm"):
            values = afms(row.get(field_name))
            if len(values) == 1:
                supplier_afm = values[0]
                break
        supplier_name = first_text(row, ["direct_name", "payment_beneficiary_name", "spending_contractors_name", "commitment_counterparty"])
        org = first_text(row, ["org", "org_name_clean", "organization"])
        observed = parse_dt(row.get("issueDate")) or parse_dt(row.get("publishTimestamp"))
        published = parse_dt(row.get("publishTimestamp")) or parse_dt(row.get("submissionTimestamp"))
        pdf_text = str(row.get("pdf_text", "") or "")
        if pdf_text.casefold() in {"nan", "none", "null"}:
            pdf_text = ""
        pdf_text = pdf_text[:120000]
        related_adas, related_adams = refs(
            subject,
            row.get("direct_related_commitment"), row.get("direct_see_also"),
            row.get("payment_related_commitment_or_spending"), row.get("payment_see_also"),
            pdf_text[:40000],
        )
        related_adas.discard(ada)
        record = Record(
            ada=ada, subject=subject, subject_n=subject_n, org=org, org_n=norm(org),
            decision_type=decision_type, stage=stg, amount=amount,
            supplier_afm=supplier_afm, supplier_name=supplier_name,
            observed=observed, published=published,
            direct=has(subject_n, DIRECT_TERMS), emergency=has(subject_n, EMERGENCY_TERMS),
            modification=has(subject_n, MODIFICATION_TERMS), routine=has(subject_n, ROUTINE_TERMS),
            medical=has(subject_n, EMERGENCY_TERMS) and has(subject_n, MEDICAL_TERMS),
            token_set=tokens(subject), topic=topic_key(subject),
            related_adas=related_adas, related_adams=related_adams, pdf_text=pdf_text,
            url=str(row.get("documentUrl", "") or "").strip(),
        )
        richness = sum(bool(item) for item in (amount, supplier_afm, supplier_name, pdf_text, related_adas, related_adams))
        old = selected.get(ada)
        old_richness = sum(bool(item) for item in (old.amount, old.supplier_afm, old.supplier_name, old.pdf_text, old.related_adas, old.related_adams)) if old else -1
        if richness > old_richness:
            selected[ada] = record
    return list(selected.values())


def procurement_like(record: Record) -> bool:
    if record.routine:
        return False
    if record.stage in {"award", "contract", "modification", "payment", "commitment"}:
        return True
    return any(term in record.subject_n for term in ("αναθεση", "συμβαση", "συμφωνητικ", "προμηθεια", "εργασι", "υπηρεσι", "αναδοχ", "διαγωνισ", "πληρωμ", "ενταλμα"))


def windows(indexes: list[int], records: list[Record], days: int = 365) -> list[tuple[int, ...]]:
    ordered = sorted(indexes, key=lambda i: records[i].observed or datetime.min)
    result: list[tuple[int, ...]] = []
    for start in range(len(ordered)):
        start_date = records[ordered[start]].observed
        group = []
        for index in ordered[start:]:
            current = records[index].observed
            if start_date and current and (current - start_date).days > days:
                break
            group.append(index)
        if len(group) >= 3:
            result.append(tuple(group))
            if len(group) >= 8:
                break
    return result[:4]


def generate(records: list[Record]) -> list[Candidate]:
    candidates: dict[frozenset[int], Candidate] = {}
    supplier: dict[tuple[str, str], list[int]] = defaultdict(list)
    topic: dict[tuple[str, str], list[int]] = defaultdict(list)
    adam: dict[str, list[int]] = defaultdict(list)
    ada_index = {record.ada: i for i, record in enumerate(records)}

    def add(indexes: Iterable[int], source: str) -> None:
        key = frozenset(indexes)
        if len(key) < 2 or len(key) > 40:
            return
        if key in candidates:
            candidates[key].source += "+" + source
        else:
            candidates[key] = Candidate(tuple(sorted(key)), source)

    for i, record in enumerate(records):
        if not procurement_like(record):
            continue
        if record.supplier_afm:
            supplier[(record.org_n, record.supplier_afm)].append(i)
        if record.topic:
            topic[(record.org_n, record.topic)].append(i)
        for value in record.related_adams:
            adam[value].append(i)

    for indexes in supplier.values():
        for group in windows(indexes, records):
            add(group, "authority_supplier_365d")
        if 2 <= len(indexes) <= 100:
            coherent = []
            for index in indexes:
                close = [other for other in indexes if other != index and jaccard(records[index].token_set, records[other].token_set) >= 0.28]
                if close:
                    coherent.append(index)
            if len(coherent) >= 2:
                add(coherent, "supplier_object_similarity")

    for indexes in topic.values():
        for group in windows(indexes, records):
            add(group, "authority_topic_365d")

    for indexes in adam.values():
        if len(set(indexes)) >= 2:
            add(set(indexes), "shared_adam")

    seen_edges: set[tuple[int, int]] = set()
    adjacency: dict[int, set[int]] = defaultdict(set)
    for i, record in enumerate(records):
        for related in record.related_adas:
            j = ada_index.get(related)
            if j is None:
                continue
            edge = tuple(sorted((i, j)))
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            adjacency[i].add(j)
            adjacency[j].add(i)
    visited: set[int] = set()
    for node in adjacency:
        if node in visited:
            continue
        stack = [node]
        component = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        if len(component) >= 2:
            add(component, "explicit_ada_chain")
    return list(candidates.values())


def score(candidate: Candidate, records: list[Record]) -> Candidate:
    cluster = [records[i] for i in candidate.indexes]
    docs = len({r.ada for r in cluster})
    amounts = [r.amount for r in cluster if r.amount is not None]
    total = sum(amounts)
    supplier_ids = {r.supplier_afm for r in cluster if r.supplier_afm}
    same_supplier = len(supplier_ids) == 1 and bool(supplier_ids)
    direct_count = sum(r.direct for r in cluster)
    emergency_count = sum(r.emergency for r in cluster)
    modification_count = sum(r.modification for r in cluster)
    link_count = sum(bool(r.related_adas or r.related_adams) for r in cluster)
    stages = {r.stage for r in cluster}
    dates = [r.observed for r in cluster if r.observed]
    span = (max(dates) - min(dates)).days if len(dates) >= 2 else 0
    pair_sims = [jaccard(cluster[i].token_set, cluster[j].token_set) for i in range(len(cluster)) for j in range(i + 1, len(cluster))]
    median_sim = statistics.median(pair_sims) if pair_sims else 0.0

    if same_supplier and docs >= 3 and median_sim >= 0.18:
        candidate.families["supplier_object_pattern"] = min(32, 25 + min(7, docs - 3))
        candidate.facts.append(f"{docs} διαφορετικά ΑΔΑ του ίδιου φορέα προς το ίδιο ΑΦΜ, με άθροισμα €{total:,.2f} και συναφείς τίτλους.")
    elif same_supplier and docs >= 4:
        candidate.families["supplier_concentration"] = min(28, 22 + min(6, docs - 4))
        candidate.facts.append(f"{docs} διαφορετικά ΑΔΑ του ίδιου φορέα προς το ίδιο ΑΦΜ, με άθροισμα €{total:,.2f}.")

    if direct_count >= 3:
        candidate.families["repeated_procedure_choice"] = min(24, 18 + direct_count)
        candidate.facts.append(f"{direct_count} αποφάσεις αναφέρουν ρητά απευθείας ανάθεση ή ισοδύναμη διαδικασία.")
    elif direct_count == 2 and docs >= 3:
        candidate.families["repeated_procedure_choice"] = 19
        candidate.facts.append("Δύο αποφάσεις της ίδιας συστάδας αναφέρουν απευθείας ανάθεση.")

    if emergency_count >= 2 and span >= 30:
        candidate.families["repeated_exception_usage"] = min(24, 18 + emergency_count)
        candidate.facts.append(f"Η επίκληση επείγοντος/έκτακτης ανάγκης επαναλαμβάνεται {emergency_count} φορές σε {span} ημέρες.")

    if modification_count >= 2:
        candidate.families["contract_change_sequence"] = min(30, 23 + modification_count * 2)
        candidate.facts.append(f"Εντοπίστηκαν {modification_count} τροποποιήσεις, παρατάσεις, ΑΠΕ ή συμπληρωματικές πράξεις.")
    elif modification_count == 1 and link_count >= 2 and len(stages) >= 2:
        candidate.families["contract_change_sequence"] = 22
        candidate.facts.append("Υπάρχει ρητή τροποποίηση/ΑΠΕ με πολλαπλές επίσημες συνδέσεις σε άλλα στάδια.")

    if len(amounts) >= 3 and median_sim >= 0.15:
        for threshold in (30000.0, 60000.0):
            near = [amount for amount in amounts if threshold * 0.82 <= amount <= threshold]
            if len(near) >= 3 and sum(near) >= threshold * 2.2:
                candidate.families["cumulative_near_band_pattern"] = min(30, 22 + len(near) * 2)
                candidate.facts.append(f"{len(near)} συναφή ποσά είναι κοντά στο εσωτερικό review band €{threshold:,.0f}, με άθροισμα €{sum(near):,.2f}.")

    by_stage: dict[str, list[float]] = defaultdict(list)
    for record in cluster:
        if record.amount is not None:
            by_stage[record.stage].append(record.amount)
    reference = [amount for stg in ("award", "contract", "commitment", "modification") for amount in by_stage.get(stg, [])]
    payments = by_stage.get("payment", [])
    if reference and payments and link_count >= 1:
        base = max(reference)
        paid = sum(payments)
        if base >= 1000 and paid > base * 1.10:
            ratio = paid / base
            candidate.families["linked_financial_consistency"] = min(32, round(24 + min(8, (ratio - 1.1) * 18)))
            candidate.facts.append(f"Οι συνδεδεμένες πληρωμές είναι €{paid:,.2f} έναντι ποσού αναφοράς €{base:,.2f} ({ratio:.2f}×).")

    if docs >= 3 and median_sim >= 0.50 and span <= 60:
        candidate.families["duplicate_or_template_burst"] = min(22, 16 + docs)
        candidate.facts.append(f"{docs} αποφάσεις σε {span} ημέρες έχουν υψηλή ομοιότητα αντικειμένου (διάμεση Jaccard {median_sim:.2f}).")

    lags = [
        (r.published - r.observed).days for r in cluster
        if r.published and r.observed and (r.published - r.observed).days > 30
    ]
    if len(lags) >= 2:
        candidate.families["publication_lag_pattern"] = min(21, 15 + len(lags) * 2)
        candidate.facts.append(f"{len(lags)} αποφάσεις δημοσιεύθηκαν με καθυστέρηση άνω των 30 ημερών.")

    candidate.pre_score = min(96, 30 + sum(candidate.families.values()))
    if any(r.medical for r in cluster):
        candidate.pre_score = min(candidate.pre_score, 59)
        candidate.caps.append("documented_medical_urgency_max_59")
    if all(r.emergency for r in cluster) and len(supplier_ids) > 1:
        candidate.pre_score = min(candidate.pre_score, 69)
        candidate.caps.append("single_emergency_event_diverse_suppliers_max_69")
    if docs < 2:
        candidate.pre_score = min(candidate.pre_score, 59)
        candidate.caps.append("single_document_max_59")
    if len(candidate.families) < 2:
        candidate.pre_score = min(candidate.pre_score, 69)
        candidate.caps.append("single_family_max_69")
    if amounts and max(amounts) < 1000 and "linked_financial_consistency" not in candidate.families:
        candidate.pre_score = min(candidate.pre_score, 49)
        candidate.caps.append("immaterial_max_49")
    candidate.final_score = candidate.pre_score
    return candidate


def fetch_detail(session: requests.Session, ada: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = session.get(DETAIL_URL.format(ada=quote(ada, safe="-")), timeout=(12, 30), headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        return (payload, None) if isinstance(payload, dict) else (None, "non_object_json")
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def pdf_text(session: requests.Session, ada: str, temp: Path) -> tuple[str, str | None]:
    path = temp / (hashlib.sha1(ada.encode(), usedforsecurity=False).hexdigest() + ".pdf")
    try:
        with session.get(PDF_URL.format(ada=quote(ada, safe="-")), timeout=(12, 45), stream=True, headers={"Accept": "application/pdf"}) as response:
            response.raise_for_status()
            size = 0
            with path.open("wb") as handle:
                for chunk in response.iter_content(65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise ValueError("pdf_too_large")
                    handle.write(chunk)
        if path.read_bytes()[:4] != b"%PDF":
            raise ValueError("not_pdf")
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:25])[:150000], None
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"
    finally:
        path.unlink(missing_ok=True)


def current(payload: dict[str, Any], ada: str) -> tuple[bool, str | None]:
    returned = str(payload.get("ada") or "").strip()
    if returned and returned != ada:
        return False, "different_ada"
    status = norm(payload.get("status"))
    if status and status not in {"published", "αναρτημενη", "αναρτημενη αποφαση"}:
        return False, "not_current_status"
    if payload.get("correctedVersionId") or payload.get("privateData") is True:
        return False, "corrected_or_private"
    return True, None


def validate(candidate: Candidate, records: list[Record], session: requests.Session, temp: Path) -> Candidate:
    cluster = sorted((records[i] for i in candidate.indexes), key=lambda r: r.observed or datetime.min)
    details: dict[str, dict[str, Any]] = {}
    detail_errors: dict[str, str] = {}
    texts: dict[str, str] = {r.ada: r.pdf_text for r in cluster if r.pdf_text}
    pdf_errors: dict[str, str] = {}

    for record in cluster[:MAX_DETAIL_DOCS]:
        payload, error = fetch_detail(session, record.ada)
        if payload is None:
            detail_errors[record.ada] = error or "unknown"
            continue
        ok, issue = current(payload, record.ada)
        if ok:
            details[record.ada] = payload
        else:
            detail_errors[record.ada] = issue or "not_current"

    for record in cluster[:MAX_PDF_DOCS]:
        if record.ada in texts:
            continue
        text, error = pdf_text(session, record.ada, temp)
        if text:
            texts[record.ada] = text
        elif error:
            pdf_errors[record.ada] = error

    combined = norm(" ".join([r.subject for r in cluster] + list(texts.values()) + [json.dumps(v, ensure_ascii=False)[:25000] for v in details.values()]))
    ordinary_hits = [term for term in ORDINARY_TERMS if norm(term) in combined]
    if any(r.medical for r in cluster):
        candidate.explanation = "Πιθανή πραγματική επείγουσα ιατρική ανάγκη ή λόγος ασφάλειας."
    elif ordinary_hits:
        candidate.explanation = "Υπάρχει ένδειξη προηγούμενης διαδικασίας, προσωρινής λύσης ή τεκμηριωμένης διοικητικής εξήγησης που χρειάζεται να σταθμιστεί."
    elif all(r.emergency for r in cluster):
        candidate.explanation = "Οι πράξεις μπορεί να αφορούν το ίδιο πραγματικό έκτακτο συμβάν πολιτικής προστασίας."
    else:
        candidate.explanation = "Οι πράξεις μπορεί να είναι νόμιμες, διακριτές ανάγκες ή διαφορετικά στάδια της ίδιας διαδικασίας."

    final = candidate.pre_score
    validation_caps: list[str] = []
    if ordinary_hits and set(candidate.families) <= {"supplier_object_pattern", "supplier_concentration", "repeated_procedure_choice", "repeated_exception_usage"}:
        final = min(final, 69)
        validation_caps.append("ordinary_explanation_neutralizes_procedure_only_pattern")
    if "μονο ωσ προσ τη διαρκεια" in combined or "δεν μεταβαλλεται το οικονομικο αντικειμενο" in combined:
        if "linked_financial_consistency" not in candidate.families and "cumulative_near_band_pattern" not in candidate.families:
            final = min(final, 74)
            validation_caps.append("duration_only_or_no_financial_change")
    supplier_ids = {r.supplier_afm for r in cluster if r.supplier_afm}
    if all(r.emergency for r in cluster) and len(supplier_ids) > 1:
        final = min(final, 69)
        validation_caps.append("single_emergency_event_diverse_suppliers")
    if not details and not texts:
        final = min(final, 79)
        validation_caps.append("no_live_detail_or_pdf_revalidation")
    if len(candidate.families) < 2 or len(cluster) < 2:
        final = min(final, 69)
        validation_caps.append("independence_gate_failed")

    candidate.final_score = int(final)
    candidate.validation = {
        "official_detail_current_count": len(details),
        "official_detail_checked_count": min(len(cluster), MAX_DETAIL_DOCS),
        "official_detail_errors": detail_errors,
        "pdf_text_count": len(texts),
        "pdf_checked_count": min(len(cluster), MAX_PDF_DOCS),
        "pdf_errors": pdf_errors,
        "ordinary_explanation_terms_found": ordinary_hits,
        "validation_caps": validation_caps,
        "evidence_complete_for_prioritisation": candidate.final_score >= MIN_SCORE and len(candidate.families) >= 2 and len(cluster) >= 2 and bool(details or texts),
    }
    return candidate


def payload(candidate: Candidate, records: list[Record], run: int, seed: int) -> dict[str, Any]:
    cluster = sorted((records[i] for i in candidate.indexes), key=lambda r: r.observed or datetime.min)
    return {
        "run": run,
        "seed": seed,
        "review_priority": candidate.final_score,
        "score_meaning": "human_review_priority_not_probability_of_wrongdoing",
        "families": candidate.families,
        "evidence_facts": candidate.facts,
        "strongest_ordinary_explanation": candidate.explanation,
        "validation": candidate.validation,
        "candidate_source": candidate.source,
        "documents": [record.public() for record in cluster],
    }


def choose(candidates: list[Candidate], records: list[Record], session: requests.Session, temp: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pre = [candidate for candidate in candidates if candidate.pre_score >= MIN_SCORE]
    selected: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    excluded: set[str] = set()
    for run, seed in enumerate(SEEDS, start=1):
        ordered = pre[:]
        random.Random(seed).shuffle(ordered)
        diag: dict[str, Any] = {"run": run, "seed": seed, "pre_gate_candidates": len(ordered), "deep_checked": 0, "rejected": []}
        found = None
        for candidate in ordered[:180]:
            candidate_adas = {records[i].ada for i in candidate.indexes}
            if candidate_adas & excluded:
                continue
            diag["deep_checked"] += 1
            validate(candidate, records, session, temp)
            if candidate.final_score >= MIN_SCORE and candidate.validation.get("evidence_complete_for_prioritisation"):
                found = payload(candidate, records, run, seed)
                excluded.update(candidate_adas)
                break
            if len(diag["rejected"]) < 35:
                diag["rejected"].append({"pre_score": candidate.pre_score, "final_score": candidate.final_score, "adas": sorted(candidate_adas)[:12], "families": candidate.families, "caps": candidate.caps, "validation_caps": candidate.validation.get("validation_caps", [])})
        if found:
            selected.append(found)
            diag["status"] = "FOUND"
            diag["selected_adas"] = [doc["ada"] for doc in found["documents"]]
            diag["selected_review_priority"] = found["review_priority"]
        else:
            diag["status"] = "NO_QUALIFYING_CASE_WITHIN_SNAPSHOT"
        diagnostics.append(diag)
    return selected, diagnostics


def write_outputs(out: Path, source_hash: str, source_size: int, source_rows: int, records: list[Record], candidates: list[Candidate], selected: list[dict[str, Any]], diagnostics: list[dict[str, Any]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    status = "COMPLETED" if len(selected) == 2 else "COMPLETED_INSUFFICIENT_RESULTS"
    result = {
        "status": status,
        "executed_at_utc": datetime.utcnow().isoformat() + "Z",
        "source": {"kind": "temporary_frozen_mirror_of_official_diavgeia_records", "url": SOURCE_URL, "sha256": source_hash, "bytes": source_size, "rows": source_rows, "scope": "available 2026 snapshot"},
        "method": {"runs": 2, "seeds": list(SEEDS), "minimum_review_priority": MIN_SCORE, "stop_each_run_at_first_passing_candidate": True, "persistent_raw_storage": False, "uses_outcome_labels_news_or_EAD": False, "score_is_probability_of_wrongdoing": False},
        "coverage": {"normalized_unique_decisions": len(records), "generated_candidate_clusters": len(candidates), "pre_gate_80_or_more": sum(c.pre_score >= MIN_SCORE for c in candidates), "selected_count": len(selected)},
        "selected": selected,
        "run_diagnostics": diagnostics,
    }
    (out / "scan_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"source_sha256": source_hash, "source_size": source_size, "rows": source_rows, "normalized_records": len(records), "candidate_count": len(candidates), "selected_count": len(selected), "raw_deleted_after_scan": True}, indent=2), encoding="utf-8")

    with (out / "scan_results.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["run", "seed", "review_priority", "ada", "organization", "subject", "stage", "amount_eur", "supplier_name", "official_url", "families"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in selected:
            for doc in case["documents"]:
                writer.writerow({"run": case["run"], "seed": case["seed"], "review_priority": case["review_priority"], "ada": doc["ada"], "organization": doc["organization"], "subject": doc["subject"], "stage": doc["stage"], "amount_eur": doc["amount_eur"], "supplier_name": doc["supplier_name"], "official_url": doc["official_url"], "families": " | ".join(case["families"])})

    lines = [
        "# Δύο ανεξάρτητα Diavgeia-only blind scans", "",
        f"**Κατάσταση:** `{status}`", f"**Raw αποφάσεις στο snapshot:** {source_rows:,}",
        f"**Μοναδικές αποφάσεις:** {len(records):,}", f"**Candidate clusters:** {len(candidates):,}",
        f"**Candidates με pre-score ≥80:** {sum(c.pre_score >= MIN_SCORE for c in candidates):,}", "",
        "> Το score είναι προτεραιότητα ανθρώπινου ελέγχου και όχι πιθανότητα παρανομίας, απάτης ή διαφθοράς.", "",
    ]
    for case in selected:
        lines.extend([f"## Run {case['run']} — seed {case['seed']} — {case['review_priority']}/100", "", f"**Evidence families:** {', '.join(case['families'])}", "", "**Συγκεκριμένα επίσημα facts:**", ""])
        lines.extend(f"- {fact}" for fact in case["evidence_facts"])
        lines.extend(["", f"**Ισχυρότερη φυσιολογική εξήγηση:** {case['strongest_ordinary_explanation']}", "", "**Έγγραφα Διαύγειας:**", ""])
        for doc in case["documents"]:
            amount = f" — €{doc['amount_eur']:,.2f}" if doc["amount_eur"] is not None else ""
            lines.append(f"- [{doc['ada']}]({doc['official_url']}) — {doc['subject']}{amount}")
        lines.append("")
    if len(selected) < 2:
        lines.extend(["## Περιορισμός", "", f"Βρέθηκαν {len(selected)} αντί για 2 περιπτώσεις. Το όριο δεν μειώθηκε.", ""])
    (out / "scan_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="scan-output")
    args = parser.parse_args()
    out = Path(args.out_dir)
    if out.exists():
        shutil.rmtree(out)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    with tempfile.TemporaryDirectory(prefix="diavgeia-blind-") as temporary:
        temp = Path(temporary)
        csv_path = temp / "source.csv"
        sha = hashlib.sha256()
        size = 0
        with session.get(SOURCE_URL, timeout=(20, 240), stream=True) as response:
            response.raise_for_status()
            with csv_path.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
        if size < 100000:
            raise RuntimeError(f"source snapshot unexpectedly small: {size}")
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, low_memory=False, on_bad_lines="skip")
        if len(frame) < 1000 or not {"ada", "subject", "status"}.issubset(frame.columns):
            raise RuntimeError(f"invalid source snapshot: rows={len(frame)}, columns={list(frame.columns)[:10]}")
        records = build_records(frame)
        candidates = [score(candidate, records) for candidate in generate(records)]
        candidates.sort(key=lambda item: item.pre_score, reverse=True)
        selected, diagnostics = choose(candidates, records, session, temp)
        write_outputs(out, sha.hexdigest(), size, len(frame), records, candidates, selected, diagnostics)
    print((out / "scan_report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
