#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tmp_tools import run_evidence_graph_hunter_v2b as hardened

base = hardened.base
base.OUT = Path("evidence-graph-v2c-fast-output")
base.SEED = 5600718
base.MAX_DEEP = 110
base.LANES = {
    "competition": ("μοναδική προσφορά", "μία προσφορά"),
    "procedure": ("απευθείας ανάθεση", "χωρίς προηγούμενη δημοσίευση"),
    "emergency": ("κατεπείγουσα ανάγκη", "λόγω κατεπείγοντος"),
    "timeline": ("αναδρομική ισχύ", "παρασχεθείσες υπηρεσίες"),
    "modification": ("5η τροποποίηση σύμβασης", "3η τροποποίηση σύμβασης"),
    "unit_price": ("τιμή μονάδας", "κλιματιστικά", "υγρό οξυγόνο", "φορητοί υπολογιστές"),
}
base.LANE_QUOTAS = {
    "competition": 24,
    "procedure": 24,
    "emergency": 18,
    "timeline": 16,
    "modification": 10,
    "unit_price": 28,
}

if __name__ == "__main__":
    base.main()
