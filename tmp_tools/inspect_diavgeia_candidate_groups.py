#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

BASE = "https://diavgeia.gov.gr"
DETAIL = BASE + "/luminapi/api/decisions/{ada}"
DOC = BASE + "/doc/{ada}"
OUT = Path("candidate-inspection-output")

GROUPS = {
    "hospital_group_99221950": [
        "61Γ246907Τ-1Λ6",
        "62ΓΣ46907Τ-ΕΜ8",
        "9ΠΩΨ46907Τ-1Υ2",
        "ΡΩΑΑ46907Τ-ΗΧΦ",
    ],
    "hospital_group_99222005": [
        "65Ν246906Ρ-ΣΣ5",
        "6ΧΞΛ46906Ρ-ΣΨ0",
        "Ρ2ΙΩ46906Ρ-ΗΣΟ",
    ],
    "hospital_group_99222000": [
        "6996469067-ΡΔ2",
        "699Ξ469067-Ο6Χ",
        "6ΙΥΘ469067-ΞΟΕ",
        "96ΙΔ469067-ΓΓΝ",
        "9818469067-ΦΝΥ",
        "9ΛΥ8469067-Δ9Ω",
        "9ΦΤΧ469067-Σ4Χ",
        "9Ψ3Τ469067-ΧΧΙ",
        "ΡΠΣΕ469067-ΨΞ8",
        "Ψ9ΗΡ469067-7ΞΕ",
        "ΨΒΑ0469067-ΗΑ9",
        "ΨΓ6Ζ469067-1ΩΓ",
        "ΨΕΨΝ469067-ΨΧ3",
        "ΨΚ6Κ469067-ΓΕΜ",
        "ΨΦΦ6469067-Ι6Λ",
    ],
    "ape_group_100049029": [
        "6Σ2Τ46ΜΓΘΓ-Θ6Ν",
        "9Τ1346ΜΓΘΓ-Η1Γ",
        "ΨΙ1546ΜΓΘΓ-9ΦΒ",
    ],
    "modification_group_55291": [
        "61Ξ6ΟΞ5Ψ-Χ5Β",
        "6ΣΛΨΟΞ5Ψ-3ΕΥ",
        "990ΔΟΞ5Ψ-3ΕΝ",
        "9ΧΞΞΟΞ5Ψ-347",
        "9ΧΧΜΟΞ5Ψ-ΘΜΒ",
        "ΕΧΗ6ΟΞ5Ψ-4ΤΥ",
        "ΡΒ8ΡΟΞ5Ψ-ΗΤ7",
        "ΨΑΤΦΟΞ5Ψ-ΙΧ3",
        "ΨΓ15ΟΞ5Ψ-02Μ",
        "ΨΖΝ5ΟΞ5Ψ-Δ9Ο",
        "ΨΝ19ΟΞ5Ψ-967",
    ],
}

KEYWORDS = (
    "χωρίς προηγούμενη δημοσίευση",
    "χωρίς δημοσίευση",
    "διαπραγμάτευση",
    "απευθείας ανάθεση",
    "μοναδική προσφορά",
    "μία προσφορά",
    "ένας προσφέρων",
    "τροποποίηση",
    "παράταση",
    "συμπληρωματική σύμβαση",
    "ανακεφαλαιωτικός πίνακας",
    "α.π.ε.",
    "απε",
    "κατεπείγον",
    "έκτακτη ανάγκη",
    "άγονος",
    "προσφυγή",
    "αναστολή",
    "προσωρινή",
    "covid",
    "ποσό",
    "φπα",
    "ανάδοχος",
    "προμηθευτής",
    "σύμβαση",
    "αδαμ",
)

ADAM_RE = re.compile(r"\b\d{2}(?:REQ|PROC|AWRD|SYMV|PAY)\d{9}\*?\b", re.I)
AFM_RE = re.compile(r"\b\d{9}\b")
AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)", re.I)
CONTRACT_RE = re.compile(r"(?:σύμβασ(?:η|ης)|συμφωνητικ(?:ό|ου))\s*(?:υπ\.?\s*αρ\.?|αρ\.?|αριθ\.?|με\s*αρ\.?)?\s*[:#]?\s*([A-Za-zΑ-Ωα-ω0-9./_-]{3,40})", re.I)


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def request(session: requests.Session, url: str, *, timeout: int = 45) -> requests.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code in {429, 502, 503, 504}:
                time.sleep(2 ** attempt)
                continue
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {last}")


def pdf_text(content: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="diavgeia-inspect-") as tmp:
        pdf = Path(tmp) / "doc.pdf"
        txt = Path(tmp) / "doc.txt"
        pdf.write_bytes(content)
        completed = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(txt)],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if completed.returncode != 0 or not txt.exists():
            return ""
        return txt.read_text(encoding="utf-8", errors="replace")[:160_000]


def excerpts(text: str) -> list[dict[str, str]]:
    compact = " ".join(text.split())
    folded = fold(compact)
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for keyword in KEYWORDS:
        needle = fold(keyword)
        start = 0
        while True:
            index = folded.find(needle, start)
            if index < 0:
                break
            left = max(0, index - 350)
            right = min(len(compact), index + len(keyword) + 700)
            excerpt = compact[left:right]
            key = fold(excerpt)[:300]
            if key not in seen:
                found.append({"keyword": keyword, "excerpt": excerpt})
                seen.add(key)
            start = index + len(needle)
            if len(found) >= 20:
                return found
    return found


def safe_extra_fields(detail: dict[str, Any]) -> dict[str, Any]:
    raw = detail.get("extraFieldValues")
    if not isinstance(raw, dict):
        return {}
    # Official public metadata only; cap recursively through JSON serialization.
    encoded = json.dumps(raw, ensure_ascii=False, default=str)
    if len(encoded) > 25_000:
        return {"truncated_json": encoded[:25_000]}
    return raw


def inspect_ada(session: requests.Session, ada: str) -> dict[str, Any]:
    encoded = quote(ada, safe="")
    detail_response = request(session, DETAIL.format(ada=encoded))
    detail_payload: dict[str, Any] = {}
    if detail_response.ok:
        parsed = detail_response.json()
        if isinstance(parsed, dict):
            detail_payload = parsed
    document_url = str(detail_payload.get("documentUrl") or DOC.format(ada=encoded))
    doc_response = request(session, document_url, timeout=60)
    content_type = doc_response.headers.get("content-type", "")
    text = pdf_text(doc_response.content) if doc_response.ok and "pdf" in content_type.casefold() else ""
    joined = "\n".join(
        [
            str(detail_payload.get("subject") or ""),
            json.dumps(safe_extra_fields(detail_payload), ensure_ascii=False, default=str),
            text,
        ]
    )
    issue_ms = detail_payload.get("issueDate")
    publish_ms = detail_payload.get("publishTimestamp")
    def ms_iso(value: Any) -> str | None:
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None
    return {
        "ada": ada,
        "detail_status": detail_response.status_code,
        "pdf_status": doc_response.status_code,
        "content_type": content_type,
        "status": detail_payload.get("status"),
        "privateData": detail_payload.get("privateData"),
        "correctedVersionId": detail_payload.get("correctedVersionId"),
        "organizationId": detail_payload.get("organizationId"),
        "subject": detail_payload.get("subject"),
        "decisionTypeId": detail_payload.get("decisionTypeId"),
        "issueDate": ms_iso(issue_ms),
        "publishTimestamp": ms_iso(publish_ms),
        "protocolNumber": detail_payload.get("protocolNumber"),
        "documentUrl": document_url,
        "extraFieldValues": safe_extra_fields(detail_payload),
        "pdf_text_length": len(text),
        "adams": sorted(set(ADAM_RE.findall(joined))),
        "adam_tokens": sorted(set(match.group(0).upper() for match in ADAM_RE.finditer(joined))),
        "contract_refs": sorted(set(match.group(1) for match in CONTRACT_RE.finditer(joined)))[:30],
        "amount_mentions": sorted(set(match.group(1) for match in AMOUNT_RE.finditer(joined)))[:50],
        "afm_mentions": sorted(set(AFM_RE.findall(joined)))[:50],
        "keyword_excerpts": excerpts(joined),
        "text_preview": " ".join(text.split())[:5000],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "MizAI temporary official-source validation/1.0", "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.1"})
    output: dict[str, Any] = {
        "status": "completed",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "source": "Diavgeia official detail and document endpoints",
        "groups": {},
    }
    for group, adas in GROUPS.items():
        items = []
        for ada in adas:
            try:
                items.append(inspect_ada(session, ada))
            except Exception as exc:  # diagnostics only
                items.append({"ada": ada, "error": type(exc).__name__, "message": str(exc)[:500]})
            time.sleep(0.35)
        output["groups"][group] = items
    (OUT / "inspection.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        name: {
            "requested": len(items),
            "successful_details": sum(isinstance(item, dict) and item.get("detail_status") == 200 for item in items),
            "readable_pdfs": sum(isinstance(item, dict) and int(item.get("pdf_text_length") or 0) > 500 for item in items),
        }
        for name, items in output["groups"].items()
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
