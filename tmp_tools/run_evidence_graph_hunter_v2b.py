#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from pathlib import Path

# When this file is executed directly, Python otherwise exposes only tmp_tools/
# on sys.path. Add the repository root so the namespace package can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tmp_tools import run_evidence_graph_hunter_v2 as base

# Independent rerun, with corrected category precedence and safer contract identity.
base.OUT = Path("evidence-graph-v2b-output")
base.SEED = 5600717
base.MAX_DEEP = 220

base.CATEGORY_RULES = (
    ("medical_gases", ("υγρο οξυγονο", "ιατρικ αερι", "φαρμακευτικ οξυγονο")),
    ("medical_waste", ("ιατρικ αποβλητ", "νοσοκομειακ αποβλητ", "εααμ", "μεα")),
    ("cleaning", ("καθαρισμ", "καθαριοτητα")),
    ("food_service", ("σιτιση", "φαγητ", "εστιασ", "τροφιμ", "γευμα")),
    ("air_conditioner", ("κλιματιστικ", "air condition", "btu")),
    ("computer", ("φορητ", "υπολογιστ", "laptop", "οθον", "εκτυπωτ")),
    ("apparel_gifts", ("γραβατ", "φουλαρ", "αναμνηστικ", "δωρ")),
    ("chemicals", ("αντιδραστηρ", "χημικ", "reagent")),
    ("construction", ("εργο", "κατασκευ", "ανακατασκευ", "οδοποι", "ασφαλτο", "επισκευη σχολ")),
    ("software", ("λογισμικ", "πληροφοριακ", "software", "εφαρμογ")),
    ("lodging", ("διανυκτερευ", "ξενοδοχει", "καταλυμα", "δωματι")),
    ("fuel", ("καυσιμ", "βενζιν", "πετρελαι", "λιπαντικ")),
)

# A bare occurrence of «πράξη» is too generic to turn a date range into a
# programme period. Keep only contextual programme/funding markers.
base.PROGRAMME_ROLE_TERMS = (
    "χρηματοδοτηση",
    "προγραμμα",
    "εσπα",
    "ππα",
    "mis",
    "ενταγμεν",
    "προγραμματικη περιοδο",
)
base.SERVICE_ROLE_TERMS = (
    *base.SERVICE_ROLE_TERMS,
    "για το χρονικο διαστημα",
    "η διαρκεια τησ παροχησ",
    "περιοδοσ παροχησ",
)


def safe_contract_ref(value: str) -> bool:
    folded = base.fold(value)
    if not any(character.isdigit() for character in value):
        return False
    if folded in {"προμηθειασ", "υπηρεσιων", "εργου", "παροχησ", "αναθεσησ"}:
        return False
    return 5 <= len(value) <= 45


def collapse_chains(records: list[base.EvidenceRecord]) -> list[base.Chain]:
    dsu = base.DSU(record.ada for record in records)
    identifiers: dict[str, list[str]] = defaultdict(list)
    for record in records:
        for adam in record.adams:
            identifiers["adam:" + adam].append(record.ada)
        for contract_ref in record.contract_refs:
            if safe_contract_ref(contract_ref):
                identifiers[
                    f"org:{record.organization_id}:contract:{contract_ref}"
                ].append(record.ada)
        for related in record.related_adas:
            if related in dsu.parent:
                identifiers["ada:" + related].extend([record.ada, related])
    for values in identifiers.values():
        for other in values[1:]:
            dsu.union(values[0], other)
    grouped: dict[str, list[base.EvidenceRecord]] = defaultdict(list)
    for record in records:
        grouped[dsu.find(record.ada)].append(record)
    chains: list[base.Chain] = []
    for items in grouped.values():
        fingerprint = hashlib.sha256(
            "|".join(sorted(record.ada for record in items)).encode()
        ).hexdigest()[:18]
        chains.append(base.Chain(chain_id=fingerprint, records=items))
    return chains


# Only real procurement-contract changes may activate the detector. Programme
# calls, budget amendments, employment-like contracts and generic agreements are
# excluded unless the subject section contains a real procurement identity.
def modification_facts(
    ada: str,
    subject: str,
    focused_pages: list[tuple[int, str]],
) -> list[base.Fact]:
    value = base.fold(subject)
    joined = subject + "\n" + "\n".join(page for _, page in focused_pages)
    joined_folded = base.fold(joined)
    excluded = (
        "τροποποιηση προκηρυξησ προγραμματοσ",
        "τροποποιηση προϋπολογισμου",
        "τροποποιηση προυπολογισμου",
        "τροποποιηση τησ υπουργικησ αποφασησ",
        "τροποποιηση υπουργικησ αποφασησ",
        "συμβασησ μεταξυ οτδ και δικαιουχου",
        "εργα που δεν υλοποιουνται με τισ διαδικασιεσ των δημοσιων συμβασεων",
        "συμβαση μισθωσησ εργου",
        "τροποποιηση συμβασησ μισθωσησ εργου",
    )
    if any(term in value for term in excluded):
        return []

    procurement_identity = (
        any("SYMV" in match.group(0).upper() for match in base.ADAM_RE.finditer(joined))
        or "cpv" in joined_folded
        or any(
            term in joined_folded
            for term in (
                "δημοσια συμβαση",
                "οικονομικοσ φορεασ",
                "αναδοχοσ",
                "προμηθευτησ",
                "συμβατικο τιμημα",
                "διαγωνισμοσ",
            )
        )
    )
    if "προγραμματικη συμβαση" in joined_folded and not procurement_identity:
        return []

    is_contract_change = (
        "τροποποιηση συμβασησ" in value
        or ("τροποποιημενου χρονοδιαγραμματοσ" in value and "συμβαση" in value)
        or "τροποποιηση) συμβασησ" in value
        or "απε" in value
    )
    if not is_contract_change or not procurement_identity:
        return []

    patterns = (
        (15, ("15η τροποποιηση",)),
        (14, ("14η τροποποιηση",)),
        (13, ("13η τροποποιηση",)),
        (12, ("12η τροποποιηση",)),
        (11, ("11η τροποποιηση",)),
        (10, ("10η τροποποιηση",)),
        (9, ("9η τροποποιηση",)),
        (8, ("8η τροποποιηση",)),
        (7, ("7η τροποποιηση",)),
        (6, ("6η τροποποιηση",)),
        (5, ("5η τροποποιηση", "πεμπτη τροποποιηση")),
        (4, ("4η τροποποιηση", "τεταρτη τροποποιηση")),
        (3, ("3η τροποποιηση", "τριτη τροποποιηση", "3ος απε", "3ου απε")),
        (2, ("2η τροποποιηση", "δευτερη τροποποιηση", "2ος απε", "2ου απε")),
        (1, ("τροποποιηση συμβασησ", "παραταση συμβασησ", "ανακεφαλαιωτικοσ πινακασ")),
    )
    rank = 0
    for candidate, phrases in patterns:
        if any(phrase in value for phrase in phrases):
            rank = max(rank, candidate)
    if rank == 0:
        return []
    return [
        base.Fact(
            fact_type="contract_change",
            value=rank,
            role="modification_rank",
            unit="ordinal",
            scope="procurement_contract_chain",
            source_ada=ada,
            source_page=focused_pages[0][0] if focused_pages else None,
            source_excerpt=base.compact(subject, 650),
            confidence=0.98,
            dependency_group="contract_change",
        )
    ]


_original_procedure_facts = base.procedure_and_context_facts


def _is_actual_single_bid_event(excerpt: str) -> bool:
    value = base.fold(excerpt)
    normative_phrases = (
        "καθε προσφερων μπορει να υποβαλει μονο μια προσφορα",
        "καθε οικονομικοσ φορεασ μπορει να υποβαλει μονο μια προσφορα",
        "μια προσφορα ανα οικονομικο φορεα",
        "δεν επιτρεπεται η υποβολη περισσοτερων προσφορων",
        "εναλλακτικεσ προσφορεσ δεν γινονται δεκτεσ",
    )
    if any(phrase in value for phrase in normative_phrases):
        return False
    event_phrases = (
        "υποβληθηκε μια προσφορα",
        "υποβληθηκε μονο μια προσφορα",
        "υποβληθηκε μοναδικη προσφορα",
        "κατατεθηκε μια προσφορα",
        "κατατεθηκε μονο μια προσφορα",
        "κατατεθηκε μοναδικη προσφορα",
        "μοναδικη συμμετεχουσα",
        "μοναδικοσ συμμετεχων",
        "τη μοναδικη προσφορα",
        "την μοναδικη προσφορα",
        "παρελαβε τη μοναδικη προσφορα",
        "παρελαβε την μοναδικη προσφορα",
        "μονο μια προσφορα κατατεθηκε",
        "μονο μια προσφορα υποβληθηκε",
        "μια μονο προσφορα",
    )
    return any(phrase in value for phrase in event_phrases)


def procedure_and_context_facts(
    ada: str,
    focused_pages: list[tuple[int, str]],
) -> list[base.Fact]:
    facts = _original_procedure_facts(ada, focused_pages)
    facts = [
        fact
        for fact in facts
        if fact.role != "single_bid" or _is_actual_single_bid_event(fact.source_excerpt)
    ]

    if not any(fact.role == "open_tender" for fact in facts):
        for page_number, page in focused_pages:
            folded = base.fold(page)
            if any(
                phrase in folded
                for phrase in (
                    "ανοικτη διαδικασια",
                    "ανοικτοσ διαγωνισμοσ",
                    "ανοικτου διαγωνισμου",
                    "διαγωνισμου με ανοικτη διαδικασια",
                )
            ):
                facts.append(
                    base.Fact(
                        fact_type="ordinary_explanation",
                        value=True,
                        role="open_tender",
                        unit="boolean",
                        scope="subject_section",
                        source_ada=ada,
                        source_page=page_number,
                        source_excerpt=base.compact(page, 650),
                        confidence=0.98,
                        dependency_group="falsification",
                    )
                )
                break
    return facts


base.collapse_chains = collapse_chains
base.modification_facts = modification_facts
base.procedure_and_context_facts = procedure_and_context_facts

if __name__ == "__main__":
    base.main()
