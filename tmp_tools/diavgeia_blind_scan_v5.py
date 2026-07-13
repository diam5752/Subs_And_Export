#!/usr/bin/env python3
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diavgeia_blind_scan_v4 as base  # noqa: E402

# A documented emergency/procedure choice is one context, not two independent facts.
base.ORDINARY_EXPLANATION_TERMS = tuple(base.ORDINARY_EXPLANATION_TERMS) + (
    "κατασταση κινητοποιησης red code",
    "κηρυξη της αττικης σε κατασταση κινητοποιησης",
    "κατεπειγουσα αναγκη οφειλομενη σε γεγονοτα απροβλεπτα",
    "λογω εκτακτου γεγονοτος πυρκαγια",
    "για την αντιμετωπιση τυχον εκτακτου γεγονοτος",
    "θεομηνια",
)


def group_score_v5(records: list[base.Rec], kind: str) -> tuple[int, dict[str, int], list[str], dict[str, Any]]:
    chains = base.chain_representatives(records)
    if len(chains) < 3:
        return 0, {}, [], {"distinct_chains": len(chains)}

    families: dict[str, int] = {}
    facts: list[str] = []
    dates = [chain["date"] for chain in chains]
    span_days = (max(dates) - min(dates)).days
    distinct_months = {(date.year, date.month) for date in dates}

    direct_count = sum(1 for chain in chains if chain["direct"])
    emergency_count = sum(1 for chain in chains if chain["emergency"])

    # Direct award + emergency are deliberately one family. A same-day RED CODE
    # deployment is one operational episode, no matter how many suppliers/documents exist.
    if direct_count >= 3 and (span_days >= 30 or len(distinct_months) >= 2):
        families["repeated_procedure_context"] = 24
        if emergency_count:
            facts.append(
                f"{direct_count} διακριτές αλυσίδες σε {len(distinct_months)} μήνες χρησιμοποιούν "
                "περιορισμένη/απευθείας διαδικασία· η επίκληση επείγοντος μετρήθηκε στην ίδια family."
            )
        else:
            facts.append(
                f"{direct_count} διακριτές αλυσίδες σε {len(distinct_months)} μήνες αναφέρουν "
                "περιορισμένη ή απευθείας διαδικασία."
            )

    by_band: dict[float, list[tuple[float, str]]] = defaultdict(list)
    for chain in chains:
        amount = chain["amount"]
        if amount is not None and (band := base.band_for(amount)) is not None:
            by_band[band].append((amount, chain["key"]))
    for band, entries in by_band.items():
        values = [amount for amount, _ in entries]
        if len(entries) >= 3 and len({key for _, key in entries}) >= 3 and sum(values) >= 1.5 * band:
            families["cumulative_near_band_pattern"] = 30
            facts.append(
                f"{len(entries)} διακριτές αλυσίδες έχουν ποσά κοντά στο εσωτερικό review band "
                f"€{band:,.0f}, με άθροισμα €{sum(values):,.2f}."
            )
            break

    pair_scores = [
        base.jaccard(left["subject"], right["subject"])
        for index, left in enumerate(chains)
        for right in chains[index + 1 :]
    ]
    median_similarity = base.statistics.median(pair_scores) if pair_scores else 0.0
    distinct_amounts = {chain["amount"] for chain in chains if chain["amount"] is not None}
    distinct_suppliers = set().union(*(chain["suppliers"] for chain in chains))
    if (
        len(chains) >= 4
        and span_days <= 45
        and median_similarity >= 0.82
        and (len(distinct_amounts) >= 2 or len(distinct_suppliers) >= 2)
    ):
        # Discovery support only: it cannot combine with procedure context alone to reach 80.
        families["duplicate_or_template_burst"] = 18
        facts.append(
            f"{len(chains)} διακριτές αλυσίδες σε {span_days} ημέρες έχουν υψηλή ομοιότητα τίτλων "
            f"(διάμεση Jaccard {median_similarity:.2f})."
        )

    supplier_counts: dict[str, int] = defaultdict(int)
    supplier_totals: dict[str, float] = defaultdict(float)
    supplier_dates: dict[str, list[Any]] = defaultdict(list)
    for chain in chains:
        for supplier in chain["suppliers"]:
            supplier_counts[supplier] += 1
            supplier_totals[supplier] += chain["amount"] or 0.0
            supplier_dates[supplier].append(chain["date"])
    if supplier_counts:
        supplier, count = max(
            supplier_counts.items(),
            key=lambda item: (item[1], supplier_totals[item[0]]),
        )
        s_dates = supplier_dates[supplier]
        supplier_span = (max(s_dates) - min(s_dates)).days if len(s_dates) > 1 else 0
        supplier_months = {(date.year, date.month) for date in s_dates}
        if (
            count >= 3
            and supplier_totals[supplier] >= 30000
            and supplier_span >= 60
            and len(supplier_months) >= 2
        ):
            families["supplier_object_pattern"] = 30
            facts.append(
                f"Το ίδιο ΑΦΜ εμφανίζεται σε {count} διακριτές αλυσίδες του ίδιου φορέα/αντικειμένου, "
                f"σε {len(supplier_months)} μήνες και συνολικό ποσό €{supplier_totals[supplier]:,.2f}."
            )

    if len(families) < 2:
        return 0, families, facts, {
            "distinct_chains": len(chains),
            "span_days": span_days,
            "distinct_months": len(distinct_months),
            "kind": kind,
        }

    score = min(94, 28 + sum(families.values()))
    return score, families, facts, {
        "distinct_chains": len(chains),
        "span_days": span_days,
        "distinct_months": len(distinct_months),
        "median_similarity": round(median_similarity, 3),
        "kind": kind,
    }


base.group_score = group_score_v5


if __name__ == "__main__":
    raise SystemExit(base.main())
