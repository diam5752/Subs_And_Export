#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tmp_tools import validate_bridge_candidates_v4 as base

AMOUNT_TOKEN = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}")
FLEX_DATE_RANGE = re.compile(
    r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})\s*"
    r"(?:εωσ|ωσ|μεχρι|-)\s*"
    r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})",
    re.I,
)


def _nearby(value: str, start: int, end: int, radius: int = 110) -> str:
    return value[max(0, start - radius): min(len(value), end + radius)]


def gross_amount(subject: str, text: str) -> tuple[float | None, str]:
    for source, raw in (("subject", subject), ("pdf", text[:40000])):
        value = base.fold(raw)
        gross_values = []
        for match in AMOUNT_TOKEN.finditer(value):
            context = _nearby(value, match.start(), match.end())
            explicitly_net = any(term in context for term in (
                "χωρισ φ", "ανευ φ", "πλεον φ", "μη συμπεριλαμβανομενου φ",
            )) and not any(term in context for term in (
                "ητοι", "διαμορφωνεται στα", "συμπεριλαμβανομενου φ", "με φ",
            ))
            explicitly_gross = any(term in context for term in (
                "συμπεριλαμβανομενου φ", "συμπ/νου φ", "με φ.π.α", "με φπα",
                "ητοι", "διαμορφωνεται στα", "συνολο με φ",
            ))
            if explicitly_gross and not explicitly_net:
                amount = base.money(match.group(0))
                if 1000 <= amount <= 5_000_000:
                    gross_values.append(amount)
        if gross_values:
            return max(gross_values), f"context_typed_gross_{source}"

    for source, raw in (("subject", subject), ("pdf", text[:40000])):
        value = base.fold(raw)
        for match in AMOUNT_TOKEN.finditer(value):
            context = value[match.end(): min(len(value), match.end() + 150)]
            if not any(term in context for term in (
                "μη συμπεριλαμβανομενου φ", "χωρισ φ", "ανευ φ", "πλεον φ",
            )):
                continue
            vat_match = re.search(r"φ\s*\.?\s*π\s*\.?\s*α\s*\.?\s*(\d{1,2})\s*%", context)
            if not vat_match:
                continue
            net = base.money(match.group(0))
            vat = int(vat_match.group(1))
            if 1000 <= net <= 5_000_000 and 1 <= vat <= 30:
                return round(net * (1 + vat / 100), 2), f"computed_from_net_vat_{source}"
    return None, "missing"


def service_period(subject: str, text: str) -> tuple[str | None, str | None]:
    for raw in (subject, text[:22000]):
        value = base.fold(raw)
        for match in FLEX_DATE_RANGE.finditer(value):
            d1, m1, y1, d2, m2, y2 = map(int, match.groups())
            try:
                left = date(y1, m1, d1)
                right = date(y2, m2, d2)
            except ValueError:
                continue
            if right < left or (right - left).days > 370:
                continue
            context = _nearby(value, match.start(), match.end(), 180)
            if not any(term in context for term in (
                "καλυψη των αναγκων", "χρονικο διαστημα", "παροχη υπηρεσιων",
                "διαρκεια", "υπηρεσιεσ καθαρισμου", "αναγκεσ τησ",
            )):
                continue
            return left.isoformat(), right.isoformat()
    return None, None


base.gross_amount = gross_amount
base.service_period = service_period

if __name__ == "__main__":
    base.main()
