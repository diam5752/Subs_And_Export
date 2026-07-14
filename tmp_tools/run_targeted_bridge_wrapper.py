#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tmp_tools import run_evidence_graph_hunter_v2b as hardened

base = hardened.base
ORIGINAL_BUILD = base.build_candidates

MODES = {
    "cleaning": {
        "lanes": {
            "competition": ("IPIROTIKI FACILITY SERVICES", "ΗΠΕΙΡΩΤΙΚΗ FACILITY SERVICES", "μοναδική προσφορά καθαρισμού"),
            "procedure": ("υπηρεσίες καθαρισμού χωρίς προηγούμενη δημοσίευση", "διαπραγμάτευση χωρίς προηγούμενη δημοσίευση καθαρισμού", "υπηρεσίες καθαριότητας διαπραγμάτευση"),
            "emergency": ("καθαρισμού κατεπείγουσα ανάγκη", "καθαριότητα κατεπείγουσα ανάγκη"),
            "timeline": ("καθαριότητα μέχρι την ολοκλήρωση του διαγωνισμού", "καθαρισμού μέχρι την υπογραφή νέας σύμβασης"),
            "modification": ("παράταση σύμβασης καθαρισμού",),
            "unit_price": (),
        },
        "quotas": {"competition": 120, "procedure": 140, "emergency": 80, "timeline": 80, "modification": 30, "unit_price": 0},
    },
    "medical_waste": {
        "lanes": {
            "competition": ("ΑΠΟΣΤΕΙΡΩΣΗ ΚΕΝΤΡΟ ΕΠΕΞΕΡΓΑΣΙΑΣ ΑΠΟΒΛΗΤΩΝ", "μοναδική προσφορά αποβλήτων"),
            "procedure": ("επικίνδυνων ιατρικών αποβλήτων χωρίς προηγούμενη δημοσίευση", "διαχείριση επικίνδυνων αποβλήτων διαπραγμάτευση", "αποκομιδή μεταφορά διάθεση επικίνδυνων αποβλήτων"),
            "emergency": ("επικίνδυνων αποβλήτων κατεπείγουσα ανάγκη",),
            "timeline": ("αποβλήτων μέχρι την ολοκλήρωση του διαγωνισμού", "αποβλήτων μέχρι την υπογραφή νέας σύμβασης"),
            "modification": ("παράταση σύμβασης αποβλήτων",),
            "unit_price": (),
        },
        "quotas": {"competition": 120, "procedure": 150, "emergency": 60, "timeline": 60, "modification": 30, "unit_price": 0},
    },
}

BRIDGE_PHRASES = (
    "μεχρι την ολοκληρωση τησ νεασ",
    "μεχρι την ολοκληρωση του διαγωνισμου",
    "εωσ την ολοκληρωση του διαγωνισμου",
    "μεχρι την υπογραφη νεασ συμβασησ",
    "εωσ την υπογραφη νεασ συμβασησ",
    "εκκρεμει η ολοκληρωση",
    "προσωρινη καλυψη",
    "προσωρινη συμβαση",
)


def add_bridge_fact(ada: str, pages: list[tuple[int, str]]) -> list[base.Fact]:
    facts = hardened.procedure_and_context_facts(ada, pages)
    if not any(f.role == "bridge_pending_tender" for f in facts):
        for page_number, page in pages:
            value = base.fold(page)
            if not any(p in value for p in BRIDGE_PHRASES):
                continue
            facts.append(base.Fact(
                fact_type="context",
                value=True,
                role="bridge_pending_tender",
                unit="boolean",
                scope="subject_section",
                source_ada=ada,
                source_page=page_number,
                source_excerpt=base.compact(page, 850),
                confidence=0.97,
                dependency_group="temporal_pattern",
            ))
            break
    return facts


def representative_amount(record: base.EvidenceRecord) -> base.Fact | None:
    return base.best_amount(record, {"award_total", "contract_total", "approved_total", "declared_total", "final_cumulative_value"})


def custom_build(chains: list[base.Chain]) -> list[dict]:
    standard = ORIGINAL_BUILD(chains)
    grouped: dict[tuple[str, str, str], list[tuple[base.Chain, base.EvidenceRecord]]] = defaultdict(list)
    for chain in chains:
        record = chain.representative
        if record.supplier_key and record.category in {"cleaning", "medical_waste"}:
            grouped[(record.organization_id, record.supplier_key, record.category)].append((chain, record))

    custom: list[dict] = []
    covered_chain_sets: list[set[str]] = []
    for values in grouped.values():
        values = sorted(values, key=lambda item: item[1].issue_date or "")
        if len(values) < 2:
            continue
        clusters: list[list[tuple[base.Chain, base.EvidenceRecord]]] = []
        for item in values:
            for cluster in clusters:
                if max(base.similarity(item[1], other[1]) for other in cluster) >= 0.16:
                    cluster.append(item)
                    break
            else:
                clusters.append([item])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            records = [record for _, record in cluster]
            exceptional = [r for r in records if base.has_role(r, "without_publication") or base.has_role(r, "emergency") or base.has_role(r, "direct_award")]
            if len(exceptional) < 2:
                continue
            dates = [date.fromisoformat(r.issue_date) for r in records if r.issue_date]
            span = (max(dates) - min(dates)).days if len(dates) >= 2 else 0
            single_bids = [r for r in records if base.has_role(r, "single_bid")]
            bridges = [r for r in records if base.has_role(r, "bridge_pending_tender") or base.has_role(r, "pending_replacement_tender")]
            amounts = [representative_amount(r) for r in records]
            amounts = [f for f in amounts if f is not None]
            total = sum(float(f.value) for f in amounts)
            families = {"procedure_pattern", "supplier_pattern"}
            if single_bids:
                families.add("competition")
            if bridges or span >= 90:
                families.add("temporal_pattern")
            reasons = [
                f"{len(records)} διαφορετικές collapsed contract chains ίδιου φορέα, αναδόχου και αντικειμένου.",
                f"{len(exceptional)} chains χρησιμοποιούν ρητά exceptional/no-publication ή emergency διαδικασία.",
                f"Το μοτίβο εκτείνεται σε {span} ημέρες.",
            ]
            if single_bids:
                reasons.append(f"Σε {len(single_bids)} chains δηλώνεται ρητά μία/μοναδική προσφορά.")
            if bridges:
                reasons.append(f"Σε {len(bridges)} chains αναφέρεται ρητά προσωρινή κάλυψη ή εκκρεμής κανονικός διαγωνισμός.")
            if amounts:
                reasons.append(f"Γνωστή αθροιστική typed αξία €{total:,.2f}.")
            ordinary = []
            for role, text in (
                ("open_tender", "Υπάρχει αναφορά σε ανοικτή/κανονική διαγωνιστική διαδικασία."),
                ("local_market_search", "Καταγράφεται αναζήτηση στην αγορά."),
                ("lowest_bidder", "Καταγράφεται επιλογή μειοδότη/χαμηλότερης προσφοράς."),
            ):
                if any(base.has_role(r, role) for r in records):
                    ordinary.append(text)
            page_ok = all(any(f.source_page is not None for f in r.facts if f.role in {"without_publication", "emergency", "single_bid", "bridge_pending_tender", "pending_replacement_tender"}) for r in exceptional)
            score_args = {
                "evidence_quality": 29 if page_ok else 24,
                "pattern_strength": 25 if len(records) >= 3 else 22,
                "peer_deviation": 12 if len(exceptional) == len(records) else 8,
                "materiality": 10 if total >= 200_000 else 8 if total >= 75_000 else 4,
                "falsification_survival": 12 if len(records) >= 3 else 9,
                "evidence_roles_complete": True,
                "page_provenance": page_ok,
                "strong_ordinary_explanation": bool(ordinary),
            }
            chain_ids = {chain.chain_id for chain, _ in cluster}
            custom.append(base.candidate(
                primary_type="repeated_bridge_exceptional_supplier",
                chain_ids=chain_ids,
                records=records[:10],
                families=families,
                reasons=reasons,
                ordinary_explanations=ordinary,
                score_args=score_args,
                metrics={
                    "chain_count": len(records),
                    "exceptional_chain_count": len(exceptional),
                    "single_bid_count": len(single_bids),
                    "bridge_count": len(bridges),
                    "span_days": span,
                    "known_typed_amount_total_eur": round(total, 2),
                },
            ))
            covered_chain_sets.append(chain_ids)

    filtered = []
    for item in standard:
        item_chains = set(item.get("chain_ids") or [])
        if any(item_chains and item_chains.issubset(covered) for covered in covered_chain_sets):
            continue
        filtered.append(item)
    return sorted([*custom, *filtered], key=lambda item: (item["novelty_rank_score"], item["review_priority"], len(item["families"])), reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-deep", type=int, default=420)
    args = parser.parse_args()
    config = MODES[args.mode]
    base.OUT = args.output
    base.SEED = args.seed
    base.MAX_DEEP = args.max_deep
    base.YEAR_WINDOWS = (("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-07-14"))
    base.LANES = config["lanes"]
    base.LANE_QUOTAS = config["quotas"]
    base.PREVIOUS_ADAS = set()
    base.procedure_and_context_facts = add_bridge_fact
    base.build_candidates = custom_build
    base.main()

if __name__ == "__main__":
    main()
