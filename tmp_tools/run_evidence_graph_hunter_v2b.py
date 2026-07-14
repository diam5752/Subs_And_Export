#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from pathlib import Path

# Running a file under tmp_tools/ makes that directory sys.path[0]. Add the
# repository root explicitly so the sibling module can be imported as a package.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


base.collapse_chains = collapse_chains

if __name__ == "__main__":
    base.main()
