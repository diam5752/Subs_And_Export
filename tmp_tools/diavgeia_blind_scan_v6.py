#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

import diavgeia_blind_scan as base

# v6 fixes the two false-positive classes observed in the previous runs:
# 1. many ADA documents belonging to one ADAM/contract were counted as many procurements;
# 2. different years or municipal units were added together without a confirmed common supplier.
# It also removes corrected/private records before rebuilding and rescoring the candidate.

SCANNER_VERSION = "diavgeia-blind-chain-aware-v6"
BASE_WRITE_OUTPUTS = base.write_outputs
HARD_FAMILIES = {
    "supplier_object_pattern",
    "contract_change_sequence",
    "explicit_chain_financial_consistency",
}
SOFT_PATTERN_FAMILIES = {
    "repeated_procedure_choice",
    "repeated_exception_usage",
    "cumulative_near_band_pattern",
    "duplicate_or_template_burst",
    "publication_lag_pattern",
}
MAX_CANDIDATE_DOCS = 28
MAX_LIVE_DETAILS = 28
MAX_LIVE_PDFS = 10

# Require a much larger payment/reference gap than ordinary VAT-basis differences.
FINANCIAL_RATIO_MIN = 1.35
FINANCIAL_ABS_MIN = 5_000.0

CONTRACT_REF_PATTERNS = (
    re.compile(
        r"(?:συμβασ(?:η|ης)|συμφωνητικ(?:ο|ου))\s*(?:αρ(?:ιθ)?\s*)?(?:πρωτ\s*)?[:.]?\s*([0-9]{2,10}/[0-9]{2,4})",
        re.I,
    ),
    re.compile(r"αρ\s*πρωτ\s*[:.]?\s*([0-9]{2,10}/[0-9]{2,4})", re.I),
)
GEO_PATTERNS = (
    re.compile(r"\bδ\s+ε\s+([α-ωa-z]+(?:\s+[α-ωa-z]+){0,2})"),
    re.compile(r"\bδημοτικ(?:η|ης)\s+ενοτητα(?:σ)?\s+([α-ωa-z]+(?:\s+[α-ωa-z]+){0,2})"),
)
ORDINARY_EXTRA_TERMS = (
    "αποβηκε αγονος",
    "προηγουμενη ανοικτη διαδικασια",
    "ανοιχτη διαδικασια",
    "μονο ως προς τη διαρκεια",
    "χωρις οικονομικη μεταβολη",
    "δεν μεταβαλλεται το οικονομικο αντικειμενο",
    "διακριτα τμηματα",
    "διαφορετικες δημοτικες ενοτητες",
)

SELF_TEST_RESULTS: dict[str, bool] = {}
GLOBAL_CHAIN_MAP: dict[int, str] = {}
GLOBAL_CHAIN_MEMBERS: dict[str, tuple[int, ...]] = {}


@dataclass(frozen=True)
class ChainSummary:
    chain_id: str
    indexes: tuple[int, ...]
    date_min: datetime | None
    date_max: datetime | None
    reference_amount: float | None
    payment_max: float | None
    supplier_ids: frozenset[str]
    direct: bool
    emergency: bool
    modification_count: int
    stages: frozenset[str]
    token_set: frozenset[str]
    geographies: frozenset[str]
    explicit_identifiers: frozenset[str]


class UnionFind:
    def __init__(self, values: Iterable[int]):
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def contract_refs(record: base.Record) -> set[str]:
    text = base.norm(" ".join([record.subject, record.pdf_text[:60_000]]))
    refs: set[str] = set()
    for pattern in CONTRACT_REF_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).strip(" .,:;-")
            if any(char.isdigit() for char in value):
                refs.add(value)
    return refs


def geography_units(record: base.Record) -> set[str]:
    text = record.subject_n
    values: set[str] = set()
    for pattern in GEO_PATTERNS:
        for match in pattern.finditer(text):
            value = " ".join(match.group(1).split()[:3]).strip()
            if value:
                values.add(value)
    return values


def build_chain_map(
    records: list[base.Record],
    indexes: Iterable[int] | None = None,
) -> tuple[dict[int, str], dict[str, tuple[int, ...]]]:
    selected = sorted(set(range(len(records)) if indexes is None else indexes))
    selected_set = set(selected)
    if not selected:
        return {}, {}

    uf = UnionFind(selected)
    by_ada = {records[index].ada: index for index in selected}

    # Explicit ADA references.
    for index in selected:
        for related in records[index].related_adas:
            other = by_ada.get(related)
            if other is not None:
                uf.union(index, other)

    # Any shared ADAM belongs to one procurement chain. This is intentionally
    # conservative: different lots under one procedure are merged rather than
    # risked as false fragmentation.
    by_adam: dict[str, list[int]] = defaultdict(list)
    for index in selected:
        for adam in records[index].related_adams:
            by_adam[adam].append(index)
    for members in by_adam.values():
        for other in members[1:]:
            uf.union(members[0], other)

    # Explicit contract/protocol references from title/PDF.
    by_contract_ref: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index in selected:
        record = records[index]
        for ref in contract_refs(record):
            by_contract_ref[(record.org_n, ref)].append(index)
    for members in by_contract_ref.values():
        for other in members[1:]:
            uf.union(members[0], other)

    raw_components: dict[int, list[int]] = defaultdict(list)
    for index in selected:
        raw_components[uf.find(index)].append(index)

    chain_map: dict[int, str] = {}
    members_by_chain: dict[str, tuple[int, ...]] = {}
    for members in raw_components.values():
        member_records = [records[index] for index in members]
        adams = sorted({adam for record in member_records for adam in record.related_adams})
        symv = [adam for adam in adams if "SYMV" in adam]
        refs = sorted({ref for record in member_records for ref in contract_refs(record)})
        if symv:
            identity = "adam:" + symv[0]
        elif adams:
            identity = "adam:" + adams[0]
        elif refs:
            identity = "contract:" + refs[0]
        else:
            identity = "ada:" + min(record.ada for record in member_records)
        digest = hashlib.sha1(identity.encode("utf-8"), usedforsecurity=False).hexdigest()[:14]
        chain_id = f"chain:{digest}:{identity[:40]}"
        ordered_members = tuple(sorted(members))
        members_by_chain[chain_id] = ordered_members
        for index in ordered_members:
            chain_map[index] = chain_id
    return chain_map, members_by_chain


def chain_summary(
    chain_id: str,
    indexes: Iterable[int],
    records: list[base.Record],
) -> ChainSummary:
    members = [records[index] for index in sorted(set(indexes))]
    dates = [record.observed for record in members if record.observed]
    references = [
        record.amount
        for record in members
        if record.amount is not None
        and record.stage in {"commitment", "award", "contract", "modification"}
    ]
    payments = [record.amount for record in members if record.amount is not None and record.stage == "payment"]
    token_set = frozenset(token for record in members for token in record.token_set)
    return ChainSummary(
        chain_id=chain_id,
        indexes=tuple(sorted(set(indexes))),
        date_min=min(dates) if dates else None,
        date_max=max(dates) if dates else None,
        reference_amount=max(references) if references else (max(payments) if payments else None),
        payment_max=max(payments) if payments else None,
        supplier_ids=frozenset(record.supplier_afm for record in members if record.supplier_afm),
        direct=any(record.direct for record in members),
        emergency=any(record.emergency for record in members),
        modification_count=len({
            (record.ada, record.subject_n)
            for record in members
            if record.modification or record.stage == "modification"
        }),
        stages=frozenset(record.stage for record in members),
        token_set=token_set,
        geographies=frozenset(unit for record in members for unit in geography_units(record)),
        explicit_identifiers=frozenset(
            [*(adam for record in members for adam in record.related_adams),
             *(ref for record in members for ref in contract_refs(record))]
        ),
    )


def summaries_for_indexes(
    records: list[base.Record],
    indexes: Iterable[int],
    chain_map: dict[int, str] | None = None,
) -> list[ChainSummary]:
    selected = tuple(sorted(set(indexes)))
    if chain_map is None:
        chain_map, _ = build_chain_map(records, selected)
    grouped: dict[str, list[int]] = defaultdict(list)
    for index in selected:
        chain_id = chain_map.get(index)
        if chain_id:
            grouped[chain_id].append(index)
    return [chain_summary(chain_id, members, records) for chain_id, members in grouped.items()]


def chain_date(summary: ChainSummary) -> datetime:
    return summary.date_min or datetime.min


def chain_windows(chain_ids: list[str], summaries: dict[str, ChainSummary], days: int) -> list[tuple[str, ...]]:
    ordered = sorted(set(chain_ids), key=lambda chain_id: chain_date(summaries[chain_id]))
    result: list[tuple[str, ...]] = []
    for start in range(len(ordered)):
        start_date = summaries[ordered[start]].date_min
        group: list[str] = []
        for chain_id in ordered[start:]:
            current = summaries[chain_id].date_min
            if start_date and current and (current - start_date).days > days:
                break
            group.append(chain_id)
        if len(group) >= 3:
            result.append(tuple(group[:10]))
    # Stable de-duplication.
    unique: list[tuple[str, ...]] = []
    seen: set[frozenset[str]] = set()
    for group in result:
        key = frozenset(group)
        if key in seen:
            continue
        seen.add(key)
        unique.append(group)
    return unique[:5]


def candidate_indexes(chain_ids: Iterable[str], members: dict[str, tuple[int, ...]]) -> tuple[int, ...]:
    indexes: list[int] = []
    for chain_id in chain_ids:
        chain_members = list(members[chain_id])
        # Keep all evidence for small chains. For large chains retain a bounded,
        # stage-diverse subset rather than arbitrary duplicates.
        if len(chain_members) > 5:
            chain_members = chain_members[:5]
        indexes.extend(chain_members)
    return tuple(sorted(set(indexes))[:MAX_CANDIDATE_DOCS])


def strict_generate(records: list[base.Record]) -> list[base.Candidate]:
    global GLOBAL_CHAIN_MAP, GLOBAL_CHAIN_MEMBERS
    GLOBAL_CHAIN_MAP, GLOBAL_CHAIN_MEMBERS = build_chain_map(records)
    summaries = {
        chain_id: chain_summary(chain_id, indexes, records)
        for chain_id, indexes in GLOBAL_CHAIN_MEMBERS.items()
    }

    candidates: dict[frozenset[int], base.Candidate] = {}

    def add(chain_ids: Iterable[str], source: str) -> None:
        indexes = candidate_indexes(chain_ids, GLOBAL_CHAIN_MEMBERS)
        key = frozenset(indexes)
        if len(key) < 2 or len(key) > MAX_CANDIDATE_DOCS:
            return
        if key in candidates:
            candidates[key].source += "+" + source
        else:
            candidates[key] = base.Candidate(tuple(sorted(key)), source)

    by_supplier: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_topic: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_org: dict[str, list[str]] = defaultdict(list)

    for chain_id, summary in summaries.items():
        representative = records[summary.indexes[0]]
        by_org[representative.org_n].append(chain_id)
        if len(summary.supplier_ids) == 1:
            supplier = next(iter(summary.supplier_ids))
            by_supplier[(representative.org_n, supplier)].append(chain_id)
        topics = Counter(records[index].topic for index in summary.indexes if records[index].topic)
        if topics:
            topic = topics.most_common(1)[0][0]
            by_topic[(representative.org_n, topic)].append(chain_id)

        # One explicit chain is only a candidate when it can support a real
        # within-chain contradiction or a modification sequence.
        if summary.modification_count >= 2 or (
            summary.payment_max is not None
            and summary.reference_amount is not None
            and summary.payment_max > summary.reference_amount * FINANCIAL_RATIO_MIN
        ):
            add([chain_id], "explicit_chain_review")

    for chain_ids in by_supplier.values():
        for group in chain_windows(chain_ids, summaries, 365):
            add(group, "distinct_chain_supplier_365d")

    for chain_ids in by_topic.values():
        for group in chain_windows(chain_ids, summaries, 180):
            add(group, "distinct_chain_topic_180d")

    # Broad authority windows are only used to expose high-similarity bursts;
    # score() still requires topic coherence and distinct chain identifiers.
    for chain_ids in by_org.values():
        for group in chain_windows(chain_ids, summaries, 60):
            if len(group) <= 10:
                add(group, "authority_distinct_chain_burst_60d")

    return list(candidates.values())


def median_chain_similarity(summaries: list[ChainSummary]) -> float:
    values = [
        base.jaccard(set(summaries[left].token_set), set(summaries[right].token_set))
        for left in range(len(summaries))
        for right in range(left + 1, len(summaries))
    ]
    return statistics.median(values) if values else 0.0


def date_span_days(summaries: list[ChainSummary]) -> int:
    dates = [summary.date_min for summary in summaries if summary.date_min]
    return (max(dates) - min(dates)).days if len(dates) >= 2 else 0


def common_supplier(summaries: list[ChainSummary]) -> str | None:
    if not summaries:
        return None
    common: set[str] | None = None
    for summary in summaries:
        values = set(summary.supplier_ids)
        if not values:
            return None
        common = values if common is None else common & values
    return sorted(common)[0] if common else None


def score_candidate(
    candidate: base.Candidate,
    records: list[base.Record],
    chain_map: dict[int, str] | None = None,
) -> base.Candidate:
    candidate.families = {}
    candidate.facts = []
    candidate.caps = []
    candidate.validation = {}

    summaries = summaries_for_indexes(records, candidate.indexes, chain_map)
    distinct_chains = len(summaries)
    similarity = median_chain_similarity(summaries)
    span = date_span_days(summaries)
    all_geographies = {unit for summary in summaries for unit in summary.geographies}

    # Repeated same supplier + coherent object must involve distinct procurement
    # chains, not many documents of one contract.
    supplier_groups: dict[str, list[ChainSummary]] = defaultdict(list)
    for summary in summaries:
        for supplier in summary.supplier_ids:
            supplier_groups[supplier].append(summary)
    best_supplier_group = max(supplier_groups.values(), key=len, default=[])
    supplier_similarity = median_chain_similarity(best_supplier_group)
    if len(best_supplier_group) >= 3 and supplier_similarity >= 0.24:
        score = min(32, 25 + min(7, len(best_supplier_group) - 3))
        candidate.families["supplier_object_pattern"] = score
        total = sum(summary.reference_amount or 0.0 for summary in best_supplier_group)
        candidate.facts.append(
            f"{len(best_supplier_group)} διαφορετικές procurement chains του ίδιου φορέα "
            f"προς το ίδιο ΑΦΜ έχουν συναφές αντικείμενο και συνολική τιμή αναφοράς €{total:,.2f}."
        )

    direct_summaries = [summary for summary in summaries if summary.direct]
    if len(direct_summaries) >= 3 and date_span_days(direct_summaries) <= 365:
        candidate.families["repeated_procedure_choice"] = min(20, 14 + len(direct_summaries))
        candidate.facts.append(
            f"{len(direct_summaries)} διαφορετικές procurement chains σε έως 365 ημέρες "
            "αναφέρουν ρητά απευθείας ανάθεση ή ισοδύναμη διαδικασία."
        )

    emergency_summaries = [summary for summary in summaries if summary.emergency]
    if len(emergency_summaries) >= 3:
        emergency_span = date_span_days(emergency_summaries)
        if 45 <= emergency_span <= 730:
            candidate.families["repeated_exception_usage"] = min(22, 15 + len(emergency_summaries))
            candidate.facts.append(
                f"Η επίκληση επείγοντος/έκτακτης ανάγκης εμφανίζεται σε "
                f"{len(emergency_summaries)} διαφορετικές chains σε {emergency_span} ημέρες."
            )

    change_chains = [
        summary
        for summary in summaries
        if summary.modification_count >= 2
        and bool(summary.stages & {"commitment", "award", "contract"})
    ]
    if change_chains:
        max_changes = max(summary.modification_count for summary in change_chains)
        candidate.families["contract_change_sequence"] = min(31, 25 + max_changes * 2)
        candidate.facts.append(
            f"Μία ρητά συνδεδεμένη σύμβαση έχει τουλάχιστον {max_changes} "
            "διακριτές τροποποιήσεις/παρατάσεις/ΑΠΕ."
        )

    # A hard financial contradiction is based on the maximum single payment,
    # never on summing repeated/cumulative payment documents. The 1.35× floor
    # avoids treating a normal ~24% VAT-basis difference as an anomaly.
    financial_anomalies: list[tuple[float, ChainSummary]] = []
    for summary in summaries:
        if summary.reference_amount is None or summary.payment_max is None:
            continue
        if summary.reference_amount < 1_000:
            continue
        difference = summary.payment_max - summary.reference_amount
        ratio = summary.payment_max / summary.reference_amount
        if ratio >= FINANCIAL_RATIO_MIN and difference >= FINANCIAL_ABS_MIN:
            financial_anomalies.append((ratio, summary))
    if financial_anomalies:
        ratio, summary = max(financial_anomalies, key=lambda item: item[0])
        candidate.families["explicit_chain_financial_consistency"] = min(
            32, round(27 + min(5, (ratio - FINANCIAL_RATIO_MIN) * 8))
        )
        candidate.facts.append(
            "Σε μία ρητά συνδεδεμένη chain, η μεγαλύτερη μεμονωμένη πληρωμή "
            f"είναι €{summary.payment_max:,.2f} έναντι τιμής αναφοράς "
            f"€{summary.reference_amount:,.2f} ({ratio:.2f}×)."
        )

    # Near-band behaviour is soft evidence. It only counts across distinct
    # chains inside 120 days and requires either a common supplier or one
    # common geographic unit. This blocks the previous Domokos false positive.
    for threshold in (30_000.0, 60_000.0):
        near = [
            summary
            for summary in summaries
            if summary.reference_amount is not None
            and threshold * 0.82 <= summary.reference_amount <= threshold
        ]
        if len(near) < 3 or date_span_days(near) > 120 or median_chain_similarity(near) < 0.35:
            continue
        near_geographies = {unit for summary in near for unit in summary.geographies}
        supplier = common_supplier(near)
        if supplier is None and len(near_geographies) > 1:
            continue
        if supplier is None and not near_geographies and median_chain_similarity(near) < 0.75:
            continue
        total = sum(summary.reference_amount or 0.0 for summary in near)
        if total < threshold * 2.2:
            continue
        candidate.families["cumulative_near_band_pattern"] = min(22, 15 + len(near) * 2)
        candidate.facts.append(
            f"{len(near)} διαφορετικές chains σε έως 120 ημέρες έχουν ποσά κοντά "
            f"στο εσωτερικό review band €{threshold:,.0f}, με άθροισμα €{total:,.2f}."
        )
        break

    if distinct_chains >= 3 and span <= 60 and similarity >= 0.75:
        candidate.families["duplicate_or_template_burst"] = min(20, 14 + distinct_chains)
        candidate.facts.append(
            f"{distinct_chains} διαφορετικές procurement chains σε {span} ημέρες "
            f"έχουν πολύ υψηλή ομοιότητα αντικειμένου (διάμεση Jaccard {similarity:.2f})."
        )

    lagged = []
    for summary in summaries:
        chain_records = [records[index] for index in summary.indexes]
        max_lag = max(
            (
                (record.published - record.observed).days
                for record in chain_records
                if record.published and record.observed and record.published >= record.observed
            ),
            default=0,
        )
        if max_lag > 45:
            lagged.append(max_lag)
    if len(lagged) >= 3:
        candidate.families["publication_lag_pattern"] = min(16, 10 + len(lagged))
        candidate.facts.append(
            f"{len(lagged)} διαφορετικές chains περιλαμβάνουν δημοσίευση με καθυστέρηση άνω των 45 ημερών."
        )

    score = min(96, 28 + sum(candidate.families.values()))
    hard = set(candidate.families) & HARD_FAMILIES

    if len(candidate.families) < 2:
        score = min(score, 69)
        candidate.caps.append("fewer_than_two_independent_families_max_69")
    if not hard:
        score = min(score, 74)
        candidate.caps.append("no_hard_family_max_74")
    if distinct_chains < 2 and not {
        "contract_change_sequence",
        "explicit_chain_financial_consistency",
    }.issubset(candidate.families):
        score = min(score, 69)
        candidate.caps.append("single_procurement_chain_max_69")
    if all_geographies and len(all_geographies) > 1 and common_supplier(summaries) is None:
        # Different municipal units can be legitimately separate scopes. They
        # may still be reviewed, but cannot reach 80 without a common supplier.
        score = min(score, 69)
        candidate.caps.append("different_geographies_without_common_supplier_max_69")
    if summaries and all(summary.emergency for summary in summaries) and span <= 14:
        score = min(score, 69)
        candidate.caps.append("single_short_emergency_event_max_69")
    if any(records[index].medical for index in candidate.indexes):
        score = min(score, 59)
        candidate.caps.append("documented_medical_urgency_max_59")

    candidate.pre_score = int(score)
    candidate.final_score = candidate.pre_score
    candidate.validation = {
        "distinct_chains_before_live_rebuild": distinct_chains,
        "hard_families_before_live_rebuild": sorted(hard),
    }
    return candidate


def strict_score(candidate: base.Candidate, records: list[base.Record]) -> base.Candidate:
    return score_candidate(candidate, records, GLOBAL_CHAIN_MAP)


def augment_record_refs(record: base.Record, detail: dict[str, Any] | None, text: str) -> None:
    payload_text = json.dumps(detail or {}, ensure_ascii=False, default=str)[:100_000]
    adas, adams = base.refs(record.subject, record.pdf_text[:50_000], text[:100_000], payload_text)
    adas.discard(record.ada)
    record.related_adas.update(adas)
    record.related_adams.update(adams)
    if text:
        record.pdf_text = text[:150_000]


def strict_validate(
    candidate: base.Candidate,
    records: list[base.Record],
    session: requests.Session,
    temp: Path,
) -> base.Candidate:
    ordered_indexes = sorted(
        set(candidate.indexes),
        key=lambda index: records[index].observed or datetime.min,
    )[:MAX_LIVE_DETAILS]

    details: dict[str, dict[str, Any]] = {}
    detail_errors: dict[str, str] = {}
    active_indexes: list[int] = []

    for index in ordered_indexes:
        record = records[index]
        detail, error = base.fetch_detail(session, record.ada)
        if detail is None:
            detail_errors[record.ada] = error or "unknown"
            continue
        ok, issue = base.current(detail, record.ada)
        if not ok:
            detail_errors[record.ada] = issue or "not_current"
            continue
        details[record.ada] = detail
        active_indexes.append(index)

    # Fetch at least one PDF per provisional chain, then additional records up
    # to the cap. Only live PDFs count toward evidence completeness.
    provisional_map, _ = build_chain_map(records, active_indexes)
    pdf_indexes: list[int] = []
    seen_chains: set[str] = set()
    for index in active_indexes:
        chain_id = provisional_map.get(index, f"ada:{records[index].ada}")
        if chain_id not in seen_chains:
            pdf_indexes.append(index)
            seen_chains.add(chain_id)
    for index in active_indexes:
        if index not in pdf_indexes:
            pdf_indexes.append(index)
    pdf_indexes = pdf_indexes[:MAX_LIVE_PDFS]

    texts: dict[str, str] = {}
    pdf_errors: dict[str, str] = {}
    for index in pdf_indexes:
        record = records[index]
        text, error = base.pdf_text(session, record.ada, temp)
        if text:
            texts[record.ada] = text
        elif error:
            pdf_errors[record.ada] = error

    for index in active_indexes:
        record = records[index]
        augment_record_refs(record, details.get(record.ada), texts.get(record.ada, ""))

    # Critical fix: corrected/private/stale records are removed first. The
    # remaining official records are then re-linked and fully rescored.
    live_chain_map, live_members = build_chain_map(records, active_indexes)
    fresh = base.Candidate(tuple(active_indexes), candidate.source)
    score_candidate(fresh, records, live_chain_map)

    candidate.indexes = fresh.indexes
    candidate.families = dict(fresh.families)
    candidate.facts = list(fresh.facts)
    candidate.caps = list(fresh.caps)
    candidate.pre_score = fresh.pre_score
    candidate.final_score = fresh.final_score

    summaries = summaries_for_indexes(records, candidate.indexes, live_chain_map)
    distinct_chains = len(summaries)
    hard = set(candidate.families) & HARD_FAMILIES
    combined = base.norm(
        " ".join(
            [records[index].subject for index in candidate.indexes]
            + list(texts.values())
            + [json.dumps(value, ensure_ascii=False, default=str)[:40_000] for value in details.values()]
        )
    )
    ordinary_hits = sorted({
        term
        for term in (*base.ORDINARY_TERMS, *ORDINARY_EXTRA_TERMS)
        if base.norm(term) in combined
    })

    validation_caps: list[str] = []
    final = candidate.final_score
    if len(active_indexes) < 2:
        final = min(final, 69)
        validation_caps.append("fewer_than_two_current_official_documents")
    if len(texts) < 2:
        final = min(final, 79)
        validation_caps.append("fewer_than_two_live_pdf_texts")
    if not hard:
        final = min(final, 74)
        validation_caps.append("no_hard_family_after_live_rebuild")
    single_chain_dual_hard = distinct_chains == 1 and {
        "contract_change_sequence",
        "explicit_chain_financial_consistency",
    }.issubset(candidate.families)
    if distinct_chains < 2 and not single_chain_dual_hard:
        final = min(final, 69)
        validation_caps.append("fewer_than_two_distinct_chains_after_live_rebuild")
    if ordinary_hits and set(candidate.families) <= (
        SOFT_PATTERN_FAMILIES | {"supplier_object_pattern"}
    ):
        final = min(final, 69)
        validation_caps.append("ordinary_explanation_neutralizes_pattern_only_case")

    candidate.final_score = int(final)
    if any(records[index].medical for index in candidate.indexes):
        candidate.explanation = "Πιθανή πραγματική επείγουσα ιατρική ανάγκη ή λόγος ασφάλειας."
    elif ordinary_hits:
        candidate.explanation = (
            "Βρέθηκε επίσημη ένδειξη προηγούμενης διαδικασίας, διακριτού scope ή άλλης "
            "συνήθους εξήγησης που μειώνει την προτεραιότητα."
        )
    elif summaries and all(summary.emergency for summary in summaries):
        candidate.explanation = "Οι πράξεις μπορεί να αφορούν ένα ή περισσότερα πραγματικά έκτακτα συμβάντα."
    else:
        candidate.explanation = (
            "Οι πράξεις μπορεί να είναι νόμιμες και διακριτές· απαιτείται ανθρώπινη ανάγνωση "
            "των μελετών, των τεχνικών scopes και των συμβατικών αλυσίδων."
        )

    evidence_complete = (
        candidate.final_score >= base.MIN_SCORE
        and len(candidate.families) >= 2
        and bool(hard)
        and len(active_indexes) >= 2
        and len(texts) >= 2
        and (distinct_chains >= 2 or single_chain_dual_hard)
    )
    candidate.validation = {
        "scanner_version": SCANNER_VERSION,
        "official_detail_current_count": len(active_indexes),
        "official_detail_checked_count": len(ordered_indexes),
        "official_detail_errors": detail_errors,
        "pdf_text_count": len(texts),
        "pdf_checked_count": len(pdf_indexes),
        "pdf_errors": pdf_errors,
        "ordinary_explanation_terms_found": ordinary_hits,
        "validation_caps": validation_caps,
        "distinct_chains_after_live_rebuild": distinct_chains,
        "live_chain_ids": sorted(live_members),
        "hard_families_after_live_rebuild": sorted(hard),
        "evidence_complete_for_prioritisation": evidence_complete,
    }
    return candidate


def strict_choose(
    candidates: list[base.Candidate],
    records: list[base.Record],
    session: requests.Session,
    temp: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pre = [candidate for candidate in candidates if candidate.pre_score >= base.MIN_SCORE]
    selected: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    excluded_chains: set[str] = set()

    for run, seed in enumerate(base.SEEDS, start=1):
        ordered = pre[:]
        random.Random(seed).shuffle(ordered)
        diag: dict[str, Any] = {
            "run": run,
            "seed": seed,
            "pre_gate_candidates": len(ordered),
            "deep_checked": 0,
            "rejected": [],
        }
        found: dict[str, Any] | None = None
        for candidate in ordered[:250]:
            provisional_chains = {
                GLOBAL_CHAIN_MAP.get(index)
                for index in candidate.indexes
                if GLOBAL_CHAIN_MAP.get(index)
            }
            if provisional_chains & excluded_chains:
                continue
            diag["deep_checked"] += 1
            strict_validate(candidate, records, session, temp)
            live_chains = set(candidate.validation.get("live_chain_ids") or [])
            if live_chains & excluded_chains:
                continue
            if (
                candidate.final_score >= base.MIN_SCORE
                and candidate.validation.get("evidence_complete_for_prioritisation")
            ):
                found = base.payload(candidate, records, run, seed)
                excluded_chains.update(live_chains)
                break
            if len(diag["rejected"]) < 50:
                diag["rejected"].append({
                    "pre_score": candidate.pre_score,
                    "final_score": candidate.final_score,
                    "adas": sorted(records[index].ada for index in candidate.indexes)[:15],
                    "families": candidate.families,
                    "caps": candidate.caps,
                    "validation_caps": candidate.validation.get("validation_caps", []),
                    "distinct_chains": candidate.validation.get("distinct_chains_after_live_rebuild"),
                })
        if found:
            selected.append(found)
            diag["status"] = "FOUND"
            diag["selected_adas"] = [document["ada"] for document in found["documents"]]
            diag["selected_review_priority"] = found["review_priority"]
        else:
            diag["status"] = "NO_QUALIFYING_CASE_WITHIN_SNAPSHOT"
        diagnostics.append(diag)
    return selected, diagnostics


def synthetic_record(
    ada: str,
    subject: str,
    amount: float | None,
    observed: datetime,
    *,
    stage: str = "award",
    supplier: str = "",
    adam: str | None = None,
    direct: bool = False,
    payment: bool = False,
) -> base.Record:
    subject_n = base.norm(subject)
    return base.Record(
        ada=ada,
        subject=subject,
        subject_n=subject_n,
        org="ΔΗΜΟΣ TEST",
        org_n=base.norm("ΔΗΜΟΣ TEST"),
        decision_type="TEST",
        stage="payment" if payment else stage,
        amount=amount,
        supplier_afm=supplier,
        supplier_name="TEST SUPPLIER" if supplier else "",
        observed=observed,
        published=observed,
        direct=direct,
        emergency=False,
        modification=stage == "modification",
        routine=False,
        medical=False,
        token_set=base.tokens(subject),
        topic=base.topic_key(subject),
        related_adas=set(),
        related_adams={adam} if adam else set(),
        pdf_text="",
        url=f"https://diavgeia.gov.gr/doc/{ada}",
    )


def run_self_tests() -> None:
    # Same ADAM must collapse to one chain.
    same_adam = [
        synthetic_record(
            f"TEST{i}-AAA",
            "Καθαρισμός δασών σύμβαση αρ πρωτ 36415/2024",
            9_100.0,
            datetime(2025, 5, 1 + i),
            stage="payment" if i == 5 else "commitment",
            adam="24SYMV015162792",
            payment=i == 5,
        )
        for i in range(6)
    ]
    chain_map, _ = build_chain_map(same_adam)
    SELF_TEST_RESULTS["same_adam_collapses_to_one_chain"] = len(set(chain_map.values())) == 1
    assert SELF_TEST_RESULTS["same_adam_collapses_to_one_chain"]

    # Different municipal units without a common supplier must not create a
    # near-band family or reach 80 from procedure + amounts.
    different_geos = [
        synthetic_record(
            f"GEO{i}-AAA",
            f"Απευθείας ανάθεση αποψίλωση κοινόχρηστων χώρων Δ.Ε. {name}",
            amount,
            datetime(2025, 4, 1 + i),
            adam=f"25SYMV00000000{i}",
            direct=True,
        )
        for i, (name, amount) in enumerate(
            [("Θεσσαλιώτιδας", 29_999.0), ("Δομοκού", 24_888.0), ("Ξυνιάδας", 24_924.0)]
        )
    ]
    geo_map, _ = build_chain_map(different_geos)
    geo_candidate = score_candidate(base.Candidate(tuple(range(3)), "test"), different_geos, geo_map)
    SELF_TEST_RESULTS["different_geographies_do_not_reach_80"] = (
        geo_candidate.pre_score < 80
        and "cumulative_near_band_pattern" not in geo_candidate.families
    )
    assert SELF_TEST_RESULTS["different_geographies_do_not_reach_80"]

    # Three distinct chains, one supplier, repeated direct procedure and a
    # true template burst can legitimately enter deep validation.
    genuine_pattern = [
        synthetic_record(
            f"SUP{i}-AAA",
            "Απευθείας ανάθεση συντήρηση πληροφοριακού συστήματος υπηρεσία υποστήριξης",
            18_000.0 + i * 500,
            datetime(2025, 6, 1 + i * 10),
            supplier="123456789",
            adam=f"25SYMV10000000{i}",
            direct=True,
        )
        for i in range(3)
    ]
    supplier_map, _ = build_chain_map(genuine_pattern)
    supplier_candidate = score_candidate(base.Candidate(tuple(range(3)), "test"), genuine_pattern, supplier_map)
    SELF_TEST_RESULTS["distinct_supplier_chains_can_enter_deep_gate"] = supplier_candidate.pre_score >= 80
    assert SELF_TEST_RESULTS["distinct_supplier_chains_can_enter_deep_gate"]

    # A 24% gross/net difference is not a hard financial contradiction.
    vat_pair = [
        synthetic_record(
            "VAT1-AAA", "Σύμβαση υπηρεσίας 100/2025", 10_000.0,
            datetime(2025, 1, 1), stage="contract", adam="25SYMV200000001"
        ),
        synthetic_record(
            "VAT2-AAA", "Πληρωμή σύμβασης 100/2025", 12_400.0,
            datetime(2025, 2, 1), stage="payment", payment=True, adam="25SYMV200000001"
        ),
    ]
    vat_map, _ = build_chain_map(vat_pair)
    vat_candidate = score_candidate(base.Candidate((0, 1), "test"), vat_pair, vat_map)
    SELF_TEST_RESULTS["vat_difference_not_hard_contradiction"] = (
        "explicit_chain_financial_consistency" not in vat_candidate.families
    )
    assert SELF_TEST_RESULTS["vat_difference_not_hard_contradiction"]

    # A single payment 1.5x above an explicitly linked reference is detected,
    # but one family alone still cannot pass 80.
    hard_pair = [
        synthetic_record(
            "HARD1-AA", "Σύμβαση υπηρεσίας 200/2025", 10_000.0,
            datetime(2025, 1, 1), stage="contract", adam="25SYMV300000001"
        ),
        synthetic_record(
            "HARD2-AA", "Πληρωμή σύμβασης 200/2025", 15_000.0,
            datetime(2025, 2, 1), stage="payment", payment=True, adam="25SYMV300000001"
        ),
    ]
    hard_map, _ = build_chain_map(hard_pair)
    hard_candidate = score_candidate(base.Candidate((0, 1), "test"), hard_pair, hard_map)
    SELF_TEST_RESULTS["real_single_payment_gap_detected_but_not_delivered_alone"] = (
        "explicit_chain_financial_consistency" in hard_candidate.families
        and hard_candidate.pre_score < 80
    )
    assert SELF_TEST_RESULTS["real_single_payment_gap_detected_but_not_delivered_alone"]


def strict_write_outputs(
    out: Path,
    source_hash: str,
    source_size: int,
    source_rows: int,
    records: list[base.Record],
    candidates: list[base.Candidate],
    selected: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> None:
    BASE_WRITE_OUTPUTS(
        out,
        source_hash,
        source_size,
        source_rows,
        records,
        candidates,
        selected,
        diagnostics,
    )
    result_path = out / "scan_results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["source"]["kind"] = "temporary_fire_protection_focused_mirror_of_official_diavgeia_records"
    result["source"]["scope"] = (
        "available fire-protection-focused snapshot; not the entire Diavgeia corpus; "
        "shortlisted ADA and PDFs revalidated live"
    )
    result["method"].update({
        "scanner_version": SCANNER_VERSION,
        "same_adam_collapsed_to_one_chain": True,
        "corrected_records_removed_before_rescore": True,
        "different_geographies_require_common_supplier_for_near_band": True,
        "payments_not_summed_for_financial_contradiction": True,
        "financial_ratio_floor": FINANCIAL_RATIO_MIN,
        "hard_family_required_for_80": True,
        "self_tests": SELF_TEST_RESULTS,
    })
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = out / "scan_report.md"
    report = report_path.read_text(encoding="utf-8")
    header = (
        f"\n**Scanner:** `{SCANNER_VERSION}`\n\n"
        "**Διορθώσεις:** κοινό ΑΔΑΜ/ρητή σύμβαση = μία chain· διορθωμένα ΑΔΑ "
        "αφαιρούνται πριν το rescore· διαφορετικές Δ.Ε. χωρίς κοινό ανάδοχο δεν "
        "δημιουργούν near-band εύρημα· οι πληρωμές δεν αθροίζονται ως δόσεις.\n\n"
        "**Εύρος:** το προσωρινό snapshot είναι εστιασμένο στην πυροπροστασία και "
        "δεν αποτελεί ολόκληρη τη Διαύγεια. Τα shortlisted έγγραφα επανελέγχθηκαν live.\n"
    )
    report_path.write_text(report.replace("\n", "\n", 1) + header, encoding="utf-8")


if __name__ == "__main__":
    run_self_tests()
    base.MAX_DETAIL_DOCS = MAX_LIVE_DETAILS
    base.MAX_PDF_DOCS = MAX_LIVE_PDFS
    base.generate = strict_generate
    base.score = strict_score
    base.validate = strict_validate
    base.choose = strict_choose
    base.write_outputs = strict_write_outputs
    raise SystemExit(base.main())
