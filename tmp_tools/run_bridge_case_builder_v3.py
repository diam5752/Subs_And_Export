#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tmp_tools import run_evidence_graph_hunter_v2b as hardened

base = hardened.base
MODE = os.environ.get("BRIDGE_MODE", "cleaning").strip()
SEED = int(os.environ.get("BRIDGE_SEED", "7701"))
OUT_NAME = os.environ.get("BRIDGE_OUT", f"bridge-case-builder-{MODE}-{SEED}")

base.OUT = Path(OUT_NAME)
base.SEED = SEED
base.MAX_DEEP = 320
base.REQUEST_SLEEP = 0.10
base.YEAR_WINDOWS = (
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
    ("2026-01-01", "2026-07-14"),
)
base.TIMELINE_REGRESSION_ADA = "ΕΞ2ΞΩΚΑ-Δ3Β"

if MODE == "cleaning":
    targeted_terms = (
        "IPIROTIKI FACILITY SERVICES",
        "ΗΠΕΙΡΩΤΙΚΗ FACILITY SERVICES",
        "υπηρεσίες καθαρισμού χωρίς προηγούμενη δημοσίευση",
        "διαπραγμάτευση χωρίς προηγούμενη δημοσίευση καθαρισμού",
        "καθαριότητα μέχρι την ολοκλήρωση του διαγωνισμού",
        "καθαρισμού κατεπείγουσα ανάγκη",
        "υπηρεσίες καθαριότητας διαπραγμάτευση",
    )
    expected_category = "cleaning"
elif MODE == "medical_waste":
    targeted_terms = (
        "επικίνδυνων ιατρικών αποβλήτων",
        "επικίνδυνων νοσοκομειακών αποβλήτων",
        "ΑΠΟΣΤΕΙΡΩΣΗ ΚΕΝΤΡΟ ΕΠΕΞΕΡΓΑΣΙΑΣ ΑΠΟΒΛΗΤΩΝ",
        "διαχείριση επικίνδυνων αποβλήτων χωρίς προηγούμενη δημοσίευση",
        "διαπραγμάτευση επικίνδυνων αποβλήτων",
        "αποκομιδή μεταφορά διάθεση επικίνδυνων αποβλήτων",
    )
    expected_category = "medical_waste"
else:
    raise SystemExit(f"unsupported BRIDGE_MODE={MODE}")

base.LANES = {
    "competition": targeted_terms[:2],
    "procedure": targeted_terms,
    "emergency": targeted_terms[-3:],
    "timeline": targeted_terms[2:5],
    "modification": (),
    "unit_price": (),
}
base.LANE_QUOTAS = {
    "competition": 100,
    "procedure": 180,
    "emergency": 100,
    "timeline": 80,
    "modification": 0,
    "unit_price": 0,
}
base.PREVIOUS_ADAS = set()

_original_inspect = base.inspect_decision

def inspect_decision(session, seed):
    record = _original_inspect(session, seed)
    if record is None:
        return None
    subject_category = base.object_category(record.subject)
    if subject_category != "other":
        record.category = subject_category
        record.signature = base.object_signature(record.subject, subject_category)
    return record

_original_supplier = base.extract_supplier
SUPPLIER_PATTERNS = (
    re.compile(r"(?:ανάδοχ(?:ο|ος|ου)|μειοδότ(?:η|ης))\s+(?:την\s+)?(?:εταιρεί(?:α|ας)\s+)?[«\"]?([^\n;,.]{5,180})", re.I),
    re.compile(r"(?:με\s+την\s+εταιρεία|της\s+εταιρείας)\s+[«\"]([^»\"]{4,180})[»\"]", re.I),
)

def extract_supplier(detail, focused_pages):
    name, key = _original_supplier(detail, focused_pages)
    if key:
        return name, key
    joined = "\n".join(page for _, page in focused_pages)
    for pattern in SUPPLIER_PATTERNS:
        match = pattern.search(joined)
        if not match:
            continue
        name = base.compact(match.group(1), 180)
        normalized = base.fold(name)
        if len(normalized) >= 4:
            return name, "name:" + hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return "", ""

_original_procedure = base.procedure_and_context_facts
BRIDGE_PHRASES = (
    "μέχρι την ολοκλήρωση του διαγωνισμού",
    "έως την ολοκλήρωση του διαγωνισμού",
    "μέχρι την ολοκλήρωση της νέας διαγωνιστικής διαδικασίας",
    "έως την ολοκλήρωση της νέας διαγωνιστικής διαδικασίας",
    "μέχρι την υπογραφή νέας σύμβασης",
    "έως την υπογραφή νέας σύμβασης",
    "προσωρινή κάλυψη",
    "προσωρινή σύμβαση",
    "εν αναμονή της ολοκλήρωσης",
    "εκκρεμεί η ολοκλήρωση",
)

def procedure_and_context_facts(ada, focused_pages):
    facts = _original_procedure(ada, focused_pages)
    if any(f.role == "bridge_pending_tender" for f in facts):
        return facts
    for page_number, page in focused_pages:
        folded = base.fold(page)
        for phrase in BRIDGE_PHRASES:
            if base.fold(phrase) not in folded:
                continue
            facts.append(base.Fact(
                fact_type="temporal_pattern",
                value=True,
                role="bridge_pending_tender",
                unit="boolean",
                scope="subject_section",
                source_ada=ada,
                source_page=page_number,
                source_excerpt=base.compact(page, 750),
                confidence=0.97,
                dependency_group="temporal_pattern",
            ))
            return facts
    return facts


def current_symv(record):
    symvs = sorted(adam.rstrip("*") for adam in record.adams if "SYMV" in adam.upper())
    return symvs[-1] if symvs else ""


def collapse_chains(records):
    dsu = base.DSU(record.ada for record in records)
    identifiers = defaultdict(list)
    for record in records:
        symv = current_symv(record)
        if symv:
            identifiers[f"org:{record.organization_id}:symv:{symv}"].append(record.ada)
        for ref in record.contract_refs:
            folded = base.fold(ref)
            if any(ch.isdigit() for ch in ref) and 5 <= len(ref) <= 45 and folded not in {"προμηθειασ", "υπηρεσιων", "εργου", "παροχησ", "αναθεσησ"}:
                identifiers[f"org:{record.organization_id}:contract:{folded}"].append(record.ada)
    for values in identifiers.values():
        for other in values[1:]:
            dsu.union(values[0], other)
    grouped = defaultdict(list)
    for record in records:
        grouped[dsu.find(record.ada)].append(record)
    chains = []
    for items in grouped.values():
        fingerprint = hashlib.sha256("|".join(sorted(item.ada for item in items)).encode()).hexdigest()[:18]
        chains.append(base.Chain(chain_id=fingerprint, records=items))
    return chains


def chain_has(chain, role):
    return any(base.has_role(record, role) for record in chain.records)


def chain_amount(chain):
    roles = {"award_total", "contract_total", "declared_total", "approved_total", "budget_total"}
    facts = []
    for record in chain.records:
        fact = base.best_amount(record, roles)
        if fact is not None:
            facts.append(fact)
    if not facts:
        return None
    return max(facts, key=lambda fact: (fact.basis == "official_metadata", fact.source_page is not None, fact.confidence, float(fact.value)))


def chain_supplier(chain):
    values = [(record.supplier_key, record.supplier_name) for record in chain.records if record.supplier_key]
    return values[0] if values else ("", "")


def chain_similarity(left, right):
    return max(base.similarity(a, b) for a in left.records for b in right.records)


def build_candidates(chains):
    output = []
    groups = defaultdict(list)
    for chain in chains:
        representative = chain.representative
        supplier_key, _ = chain_supplier(chain)
        if representative.organization_id and supplier_key and representative.category == expected_category:
            groups[(representative.organization_id, supplier_key, representative.category)].append(chain)

    for (_, _, category), values in groups.items():
        values = sorted(values, key=lambda chain: chain.representative.issue_date or "")
        clusters = []
        for chain in values:
            target = None
            for cluster in clusters:
                if max(chain_similarity(chain, existing) for existing in cluster) >= 0.16:
                    target = cluster
                    break
            if target is None:
                target = []
                clusters.append(target)
            target.append(chain)

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            procedure_chains = [c for c in cluster if chain_has(c, "without_publication") or chain_has(c, "emergency") or chain_has(c, "direct_award")]
            if len(procedure_chains) < 2:
                continue
            single_bid_chains = [c for c in cluster if chain_has(c, "single_bid")]
            bridge_chains = [c for c in cluster if chain_has(c, "bridge_pending_tender")]
            dated = [date.fromisoformat(c.representative.issue_date) for c in cluster if c.representative.issue_date]
            span = (max(dated) - min(dated)).days if len(dated) >= 2 else 0
            amounts = [chain_amount(c) for c in cluster]
            amounts = [f for f in amounts if f is not None]
            cumulative = sum(float(f.value) for f in amounts)
            page_provenance = all(
                any(f.source_page is not None for record in c.records for f in record.facts if f.role in {"without_publication", "emergency", "direct_award", "single_bid", "bridge_pending_tender"})
                for c in procedure_chains
            )
            ordinary = []
            if any(chain_has(c, "open_tender") for c in cluster):
                ordinary.append("Υπάρχει ανοικτός/νέος διαγωνισμός στο επίσημο ιστορικό.")
            if any(chain_has(c, "pending_replacement_tender") for c in cluster):
                ordinary.append("Η προσωρινή λύση συνδέεται με εκκρεμή νέα διαδικασία.")
            if any(chain_has(c, "local_market_search") for c in cluster):
                ordinary.append("Σε τουλάχιστον μία chain αναφέρεται έρευνα αγοράς.")
            if any(chain_has(c, "lowest_bidder") for c in cluster):
                ordinary.append("Σε τουλάχιστον μία chain αναφέρεται μειοδότης/χαμηλότερη προσφορά.")

            families = {"procedure_pattern", "supplier_pattern"}
            if single_bid_chains:
                families.add("competition")
            if bridge_chains or span >= 90:
                families.add("temporal_pattern")

            evidence_quality = 30 if page_provenance else 25
            pattern_strength = 25 if len(cluster) >= 3 else 22
            peer_deviation = 18 if len(procedure_chains) == len(cluster) and len(cluster) >= 3 else 13
            materiality = 10 if cumulative >= 200_000 else 8 if cumulative >= 75_000 else 5
            falsification_survival = 13 if len(cluster) >= 3 else 10
            if len(ordinary) >= 3:
                falsification_survival -= 3
            elif len(ordinary) >= 1:
                falsification_survival -= 1

            records = [record for chain in cluster for record in chain.records]
            reasons = [
                f"{len(cluster)} διαφορετικές contract chains ίδιου φορέα, αναδόχου και αντικειμένου.",
                f"{len(procedure_chains)} chains χρησιμοποιούν ρητά exceptional/no-publication, emergency ή direct-award διαδικασία.",
            ]
            if span:
                reasons.append(f"Το επαναλαμβανόμενο pattern εκτείνεται σε {span} ημέρες.")
            if single_bid_chains:
                reasons.append(f"Σε {len(single_bid_chains)} chains δηλώνεται ρητά μία/μοναδική προσφορά.")
            if bridge_chains:
                reasons.append(f"Σε {len(bridge_chains)} chains υπάρχει ρητή bridge/pending-tender διατύπωση.")
            if amounts:
                reasons.append(f"Γνωστή typed σωρευτική αξία: €{cumulative:,.2f}.")

            output.append(base.candidate(
                primary_type="repeated_bridge_exceptional_supplier",
                chain_ids={chain.chain_id for chain in cluster},
                records=records[:12],
                families=families,
                reasons=reasons,
                ordinary_explanations=ordinary,
                score_args={
                    "evidence_quality": evidence_quality,
                    "pattern_strength": pattern_strength,
                    "peer_deviation": peer_deviation,
                    "materiality": materiality,
                    "falsification_survival": max(0, falsification_survival),
                    "evidence_roles_complete": True,
                    "page_provenance": page_provenance,
                    "strong_ordinary_explanation": False,
                },
                metrics={
                    "mode": MODE,
                    "category": category,
                    "chain_count": len(cluster),
                    "procedure_chain_count": len(procedure_chains),
                    "single_bid_chain_count": len(single_bid_chains),
                    "bridge_chain_count": len(bridge_chains),
                    "span_days": span,
                    "known_typed_cumulative_amount_eur": round(cumulative, 2),
                },
            ))

    for chain in chains:
        record = chain.representative
        if record.category != expected_category or not chain_has(chain, "single_bid"):
            continue
        amount = chain_amount(chain)
        output.append(base.candidate(
            primary_type="explicit_single_bid",
            chain_ids={chain.chain_id},
            records=chain.records,
            families={"competition"},
            reasons=["Το επίσημο subject section αναφέρει πραγματικό single-bid event."],
            ordinary_explanations=[explanation for role, explanation in (
                ("open_tender", "Η διαδικασία ήταν ανοικτή."),
                ("lowest_bidder", "Το έγγραφο αναφέρει μειοδότη."),
            ) if chain_has(chain, role)],
            score_args={
                "evidence_quality": 28,
                "pattern_strength": 15,
                "peer_deviation": 0,
                "materiality": 7 if amount and float(amount.value) >= 100_000 else 3,
                "falsification_survival": 6,
                "evidence_roles_complete": True,
                "page_provenance": True,
                "strong_ordinary_explanation": False,
            },
            metrics={"mode": MODE, "known_amount_eur": float(amount.value) if amount else None},
        ))
    return base.merge_case_candidates(output)


def discovery_score(lane, subject):
    value = base.fold(subject)
    score = {"competition": 38, "procedure": 35, "emergency": 35, "timeline": 30, "modification": 0, "unit_price": 0}[lane]
    if expected_category == "cleaning" and any(term in value for term in ("καθαρισμ", "καθαριοτητα", "facility")):
        score += 20
    if expected_category == "medical_waste" and any(term in value for term in ("αποβλητ", "εααμ", "μεα")):
        score += 20
    if any(term in value for term in ("χωρισ προηγουμενη δημοσιευση", "κατεπειγουσα", "μοναδικη προσφορα", "διαπραγματευση")):
        score += 8
    return score

base.inspect_decision = inspect_decision
base.extract_supplier = extract_supplier
base.procedure_and_context_facts = procedure_and_context_facts
base.collapse_chains = collapse_chains
base.build_candidates = build_candidates
base.discovery_score = discovery_score

if __name__ == "__main__":
    base.main()
