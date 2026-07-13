#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict

import diavgeia_blind_scan as base

ORIGINAL_SCORE = base.score


def explicit_components(cluster: list[base.Record]) -> list[list[base.Record]]:
    parent = list(range(len(cluster)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_ada = {record.ada: index for index, record in enumerate(cluster)}
    for index, record in enumerate(cluster):
        for related in record.related_adas:
            other = by_ada.get(related)
            if other is not None:
                union(index, other)

    by_adam: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(cluster):
        for adam in record.related_adams:
            by_adam[adam].append(index)
    for indexes in by_adam.values():
        for other in indexes[1:]:
            union(indexes[0], other)

    components: dict[int, list[base.Record]] = defaultdict(list)
    for index, record in enumerate(cluster):
        components[find(index)].append(record)
    return [records for records in components.values() if len(records) >= 2]


def explicit_linked_financial_anomaly(cluster: list[base.Record]):
    best = None
    for component in explicit_components(cluster):
        references = [
            record.amount
            for record in component
            if record.amount is not None
            and record.stage in {"commitment", "award", "contract", "modification"}
        ]
        payments = [
            record.amount
            for record in component
            if record.amount is not None and record.stage == "payment"
        ]
        if not references or not payments:
            continue
        reference = max(references)
        payment_total = sum(payments)
        if reference < 1000 or payment_total <= reference * 1.10:
            continue
        ratio = payment_total / reference
        item = {
            "ratio": ratio,
            "reference": reference,
            "payment_total": payment_total,
            "adas": [record.ada for record in component],
        }
        if best is None or item["ratio"] > best["ratio"]:
            best = item
    return best


def corrected_score(candidate: base.Candidate, records: list[base.Record]) -> base.Candidate:
    candidate = ORIGINAL_SCORE(candidate, records)
    cluster = [records[index] for index in candidate.indexes]

    # Never compare every payment in a similarity cluster against the largest
    # award/commitment. Only an explicit ADA/ADAM-linked component may produce
    # a financial-consistency risk family.
    candidate.families.pop("linked_financial_consistency", None)
    candidate.facts = [
        fact for fact in candidate.facts
        if not fact.startswith("Οι συνδεδεμένες πληρωμές")
    ]

    anomaly = explicit_linked_financial_anomaly(cluster)
    if anomaly is not None:
        ratio = anomaly["ratio"]
        candidate.families["explicit_chain_financial_consistency"] = min(
            32,
            round(24 + min(8, (ratio - 1.10) * 18)),
        )
        candidate.facts.append(
            "Σε μία ρητά συνδεδεμένη αλυσίδα ADA/ADAM, οι πληρωμές "
            f"αθροίζονται σε €{anomaly['payment_total']:,.2f} έναντι "
            f"ποσού αναφοράς €{anomaly['reference']:,.2f} ({ratio:.2f}×)."
        )

    docs = len({record.ada for record in cluster})
    supplier_ids = {record.supplier_afm for record in cluster if record.supplier_afm}
    amounts = [record.amount for record in cluster if record.amount is not None]

    candidate.caps = []
    score = min(96, 30 + sum(candidate.families.values()))
    if any(record.medical for record in cluster):
        score = min(score, 59)
        candidate.caps.append("documented_medical_urgency_max_59")
    if all(record.emergency for record in cluster) and len(supplier_ids) > 1:
        score = min(score, 69)
        candidate.caps.append("single_emergency_event_diverse_suppliers_max_69")
    if docs < 2:
        score = min(score, 59)
        candidate.caps.append("single_document_max_59")
    if len(candidate.families) < 2:
        score = min(score, 69)
        candidate.caps.append("single_family_max_69")
    if amounts and max(amounts) < 1000 and "explicit_chain_financial_consistency" not in candidate.families:
        score = min(score, 49)
        candidate.caps.append("immaterial_max_49")

    candidate.pre_score = int(score)
    candidate.final_score = candidate.pre_score
    return candidate


if __name__ == "__main__":
    base.score = corrected_score
    raise SystemExit(base.main())
