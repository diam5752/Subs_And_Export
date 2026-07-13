#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mizas_hunter_v6 as v6  # noqa: E402

base = v6.base
MIN_SCORE = 80
RUN_SEEDS = (7411, 7412, 7413)

OBJECT_STOPWORDS = {
    "ερευνα", "αγορασ", "αγορα", "προσκληση", "εκδηλωσησ", "εκδηλωση",
    "ενδιαφεροντοσ", "ενδιαφεροντος", "προμηθεια", "προμηθειασ", "παροχη",
    "υπηρεσιων", "εργασιων", "διαδικασια", "απευθειασ", "αναθεσησ", "αναθεση",
    "επειγουσα", "επειγον", "θεμα", "αποφαση", "του", "τησ", "των", "για",
    "στο", "στη", "στην", "και", "με", "γν", "νοσοκομειου", "λασιθιου",
    "οργανικη", "μοναδα", "εδρασ", "αγιοσ", "νικολαοσ",
}

SINGLE_BID_TERMS = v6.SINGLE_BID_TERMS
NO_PUBLICATION_TERMS = v6.NO_PUBLICATION_TERMS


def object_key(subject: str) -> str:
    normalized = base.norm(subject)
    normalized = re.sub(
        r"\b(?:επειγουσα\s+)?ερευνα\s+αγορασ\s+προσκληση\s+εκδηλωσησ\s+ενδιαφεροντοσ\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\bμε\s+την\s+διαδικασια\s+τησ\s+απευθειασ\s+αναθεσησ\b", " ", normalized)
    words: list[str] = []
    for token in normalized.split():
        if token in OBJECT_STOPWORDS or token.isdigit():
            continue
        if token == "μη":
            words.append(token)
            continue
        if len(token) < 4:
            continue
        stem = token[:10]
        if stem not in words:
            words.append(stem)
    return " ".join(words[:5]) if words else "generic"


def actual_text(payload: dict[str, Any]) -> str:
    return base.norm(
        f"{payload.get('subject') or ''} "
        f"{payload.get('decisionTypeId') or ''} "
        f"{json.dumps(payload.get('extraFieldValues') or {}, ensure_ascii=False, default=str)}"
    )


def payload_to_rec_v7(payload: dict[str, Any], lens: str = ""):
    # Passing an empty lens is essential: a search term must never become evidence.
    rec = v6._ORIGINAL_PAYLOAD_TO_REC(payload, "") if hasattr(v6, "_ORIGINAL_PAYLOAD_TO_REC") else v6.payload_to_rec(payload, "")
    if rec is None:
        return None
    hay = actual_text(payload)
    title_hay = base.norm(f"{rec.subject} {rec.decision_type}")
    rec.direct = base.contains(hay, base.DIRECT_TERMS)
    rec.emergency = base.contains(hay, base.EMERGENCY_TERMS)
    rec.single_bid = base.contains(hay, SINGLE_BID_TERMS)
    rec.no_publication = base.contains(hay, NO_PUBLICATION_TERMS)
    # Modification is a document/event type, not a word found in boilerplate.
    rec.modification = base.contains(title_hay, base.MODIFICATION_TERMS)
    rec.topic = object_key(rec.subject)
    rec.publish_lag_days = 0  # Disabled until typed publication-date semantics are validated.
    rec.lens = lens
    return rec


# Preserve the unpatched function once, including when the module is reloaded.
if not hasattr(v6, "_ORIGINAL_PAYLOAD_TO_REC"):
    v6._ORIGINAL_PAYLOAD_TO_REC = v6.payload_to_rec
v6.payload_to_rec = payload_to_rec_v7


def chain_has(chain: dict[str, Any], terms: Iterable[str]) -> bool:
    return any(base.contains(base.norm(doc.combined_text()), terms) for doc in chain["docs"])


def group_score_v7(records, kind: str):
    chains = base.chain_representatives(records)
    if len(chains) < 3:
        return 0, {}, [], {"distinct_chains": len(chains), "kind": kind}
    if all(getattr(doc, "topic", "generic") == "generic" for doc in records):
        return 0, {}, [], {"distinct_chains": len(chains), "kind": kind, "cap": "generic_object"}

    families: dict[str, int] = {}
    facts: list[str] = []
    dates = [chain["date"] for chain in chains]
    span = (max(dates) - min(dates)).days
    months = {(value.year, value.month) for value in dates}

    single = sum(chain_has(chain, SINGLE_BID_TERMS) for chain in chains)
    no_pub = sum(chain_has(chain, NO_PUBLICATION_TERMS) for chain in chains)
    direct = sum(chain_has(chain, base.DIRECT_TERMS) for chain in chains)
    if single >= 2:
        families["repeated_single_bid"] = 32
        facts.append(f"{single} διακριτές αλυσίδες αναφέρουν ρητά μία ή μοναδική προσφορά.")
    elif no_pub >= 2 and span >= 30:
        families["repeated_no_publication"] = 28
        facts.append(f"{no_pub} διακριτές αλυσίδες σε {len(months)} μήνες χρησιμοποιούν διαδικασία χωρίς προηγούμενη δημοσίευση.")
    elif direct >= 3 and (span >= 60 or len(months) >= 3):
        families["repeated_limited_procedure"] = 22
        facts.append(f"{direct} διακριτές αλυσίδες σε {len(months)} μήνες χρησιμοποιούν απευθείας/περιορισμένη διαδικασία.")

    supplier_counts: Counter[str] = Counter()
    supplier_totals: defaultdict[str, float] = defaultdict(float)
    supplier_dates: defaultdict[str, list[Any]] = defaultdict(list)
    for chain in chains:
        for supplier in chain["suppliers"]:
            supplier_counts[supplier] += 1
            supplier_totals[supplier] += chain["amount"] or 0.0
            supplier_dates[supplier].append(chain["date"])
    if supplier_counts:
        supplier, count = max(supplier_counts.items(), key=lambda item: (item[1], supplier_totals[item[0]]))
        s_dates = supplier_dates[supplier]
        s_span = (max(s_dates) - min(s_dates)).days if len(s_dates) > 1 else 0
        if count >= 3 and count / len(chains) >= 0.5 and supplier_totals[supplier] >= 30000 and s_span >= 60:
            families["supplier_object_concentration"] = 30
            facts.append(
                f"Το ίδιο ΑΦΜ εμφανίζεται σε {count}/{len(chains)} διακριτές αλυσίδες του ίδιου ειδικού αντικειμένου, "
                f"σε {s_span} ημέρες και συνολικό ποσό €{supplier_totals[supplier]:,.2f}."
            )

    by_year_band: defaultdict[tuple[int, float], list[float]] = defaultdict(list)
    for chain in chains:
        amount = chain["amount"]
        if amount is not None and (band := base.band_for(amount)) is not None:
            by_year_band[(chain["date"].year, band)].append(amount)
    for (year, band), values in by_year_band.items():
        if len(values) >= 3 and sum(values) >= 1.5 * band:
            families["cumulative_near_band_pattern"] = 28
            facts.append(
                f"Το {year}, {len(values)} διακριτές αλυσίδες του ίδιου ειδικού αντικειμένου είναι κοντά "
                f"στο εσωτερικό review band €{band:,.0f}, συνολικά €{sum(values):,.2f}."
            )
            break

    by_day: defaultdict[Any, list[dict[str, Any]]] = defaultdict(list)
    for chain in chains:
        by_day[chain["date"].date()].append(chain)
    for day, items in by_day.items():
        total = sum(item["amount"] or 0 for item in items)
        amounts = {item["amount"] for item in items if item["amount"] is not None}
        suppliers = set().union(*(item["suppliers"] for item in items))
        if len(items) >= 3 and total >= 30000 and (len(amounts) >= 2 or len(suppliers) >= 2):
            families["same_day_parallel_awards"] = 24
            facts.append(f"{len(items)} διακριτές συναφείς αλυσίδες εμφανίζονται την {day.isoformat()}, συνολικά €{total:,.2f}.")
            break

    modification_chains = [
        chain for chain in chains
        if any(getattr(doc, "modification", False) for doc in chain["docs"])
    ]
    if len(modification_chains) >= 3:
        families["repeated_modification_pattern"] = 24
        facts.append(f"{len(modification_chains)} διακριτές αλυσίδες του ίδιου ειδικού αντικειμένου είναι πράξεις τροποποίησης ή παράτασης.")

    if len(families) < 2:
        return 0, families, facts, {"distinct_chains": len(chains), "span_days": span, "kind": kind}
    score = min(95, 28 + sum(families.values()))
    return score, families, facts, {
        "distinct_chains": len(chains), "span_days": span,
        "distinct_months": len(months), "kind": kind,
    }


base.group_score = group_score_v7
v6.group_score_v6 = group_score_v7


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="hunter-output-v7")
    args = parser.parse_args()
    base.MIN_SCORE = MIN_SCORE
    base.MAX_DEEP_CHECKS_PER_RUN = 40
    selected_all: list[dict[str, Any]] = []
    run_diags: list[dict[str, Any]] = []
    best_leads: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="mizas-hunter-v7-"):
        for number, seed in enumerate(RUN_SEEDS, start=1):
            records, scan_diag, live = v6.scan_pool(seed)
            # Recompute object keys after every merge/expansion.
            for record in records:
                record.topic = object_key(record.subject)
                record.publish_lag_days = 0
            candidates = v6.build_candidates_v6(records)
            best_leads.extend([
                {
                    "key": item.key, "pre_score": item.score,
                    "families": item.families, "facts": item.facts,
                    "adas": sorted(item.ada_set()),
                }
                for item in candidates[:12]
            ])
            base.SEEDS = (seed,)
            selected, diagnostics = base.run_scans(records, candidates)
            v6.label_selected(selected, live)
            selected_all.extend(selected)
            diag = diagnostics[0] if diagnostics else {"status": "NO_DIAGNOSTIC"}
            run_diags.append({
                "run": number, "seed": seed, "status": diag.get("status"),
                "records": len(records), "candidates": len(candidates),
                "pre_gate": sum(item.score >= MIN_SCORE for item in candidates),
                "search_requests": scan_diag["search_requests"],
                "network_errors": scan_diag["network_errors"][:10],
                "deep_checked": diag.get("deep_checked"),
                "selected_score": diag.get("selected_review_priority"),
                "selected_adas": diag.get("selected_adas"),
            })
            if selected:
                break

    unique: dict[str, dict[str, Any]] = {}
    for lead in best_leads:
        key = "|".join(lead["adas"]) or lead["key"]
        if key not in unique or lead["pre_score"] > unique[key]["pre_score"]:
            unique[key] = lead
    leads = sorted(unique.values(), key=lambda item: item["pre_score"], reverse=True)
    v6.write_results(Path(args.out_dir), selected_all[:1], run_diags, leads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
