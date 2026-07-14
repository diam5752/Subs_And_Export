#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

BASE = "https://diavgeia.gov.gr"
SEARCH = BASE + "/luminapi/opendata/search"
DETAIL = BASE + "/luminapi/api/decisions/{ada}"
DOC = BASE + "/doc/{ada}"
OUT = Path("candidate-neighborhood-output")
DATE_FROM = "2023-01-01"
DATE_TO = "2026-07-14"

NEIGHBORHOODS = {
    "ippokrateio_cleaning_and_food": [
        "24SYMV014127327",
        "24SYMV014612359",
        "998309282",
        "ΥΠΗΡΕΣΙΕΣ ΚΑΘΑΡΙΣΜΟΥ ΚΤΙΡΙΩΝ",
        "Διανομής και Παρασκευής Φαγητού",
    ],
    "oak_apselemis_section_1": [
        "24SYMV016040788",
        "17350/19-12-2024",
        "ΕΕΝ Αποσελέμη",
    ],
}

ADAM_RE = re.compile(r"\b\d{2}(?:REQ|PROC|AWRD|SYMV|PAY)\d{9}\*?\b", re.I)
AFM_RE = re.compile(r"\b\d{9}\b")
AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|ευρώ|eur)", re.I)

CONTEXT_TERMS = (
    "χωρίς προηγούμενη δημοσίευση",
    "διαπραγμάτευση",
    "απευθείας ανάθεση",
    "1η τροποποίηση",
    "πρώτη τροποποίηση",
    "2η τροποποίηση",
    "δεύτερη τροποποίηση",
    "τροποποίηση",
    "παράταση",
    "αρχικό ποσό",
    "συνολικό ποσό",
    "αύξηση",
    "καθαρισμού",
    "παρασκευής φαγητού",
    "ανοικτός ηλεκτρονικός διαγωνισμός",
    "άγονος",
    "αναμένεται να ολοκληρωθεί",
    "24SYMV016040788",
    "24SYMV014127327",
    "24SYMV014612359",
)


def fold(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold())
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def get(session: requests.Session, url: str, *, params: dict[str, Any] | None = None, timeout: int = 45) -> requests.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(url, params=params, timeout=timeout, allow_redirects=True)
            if response.status_code in {429, 502, 503, 504}:
                time.sleep(2 ** attempt)
                continue
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {last}")


def extract_pdf(content: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="diavgeia-neighbor-") as tmp:
        pdf = Path(tmp) / "doc.pdf"
        txt = Path(tmp) / "doc.txt"
        pdf.write_bytes(content)
        completed = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(txt)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
            check=False,
        )
        if completed.returncode != 0 or not txt.exists():
            return ""
        return txt.read_text(encoding="utf-8", errors="replace")[:180_000]


def contexts(text: str, terms: list[str]) -> list[dict[str, str]]:
    compact = " ".join(text.split())
    folded = fold(compact)
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for term in [*terms, *CONTEXT_TERMS]:
        needle = fold(term)
        if len(needle) < 3:
            continue
        start = 0
        while len(output) < 20:
            index = folded.find(needle, start)
            if index < 0:
                break
            left = max(0, index - 280)
            right = min(len(compact), index + len(term) + 650)
            excerpt = compact[left:right]
            key = fold(excerpt)[:260]
            if key not in seen:
                output.append({"term": term, "excerpt": excerpt})
                seen.add(key)
            start = index + len(needle)
    return output


def search_term(session: requests.Session, term: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for page in range(3):
        response = get(session, SEARCH, params={
            "page": page,
            "size": 100,
            "term": term,
            "from_issue_date": DATE_FROM,
            "to_issue_date": DATE_TO,
        })
        if not response.ok:
            break
        payload = response.json()
        decisions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(decisions, list) or not decisions:
            break
        found.extend(item for item in decisions if isinstance(item, dict))
        if len(decisions) < 100:
            break
        time.sleep(0.3)
    return found


def ms_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def inspect(session: requests.Session, seed_terms: list[str], record: dict[str, Any]) -> dict[str, Any]:
    ada = str(record.get("ada") or "")
    encoded = quote(ada, safe="")
    detail_response = get(session, DETAIL.format(ada=encoded))
    detail = detail_response.json() if detail_response.ok else record
    if not isinstance(detail, dict):
        detail = record
    document_url = str(detail.get("documentUrl") or DOC.format(ada=encoded))
    pdf_response = get(session, document_url, timeout=60)
    text = extract_pdf(pdf_response.content) if pdf_response.ok and "pdf" in pdf_response.headers.get("content-type", "").casefold() else ""
    extra = detail.get("extraFieldValues") if isinstance(detail.get("extraFieldValues"), dict) else {}
    joined = "\n".join([str(detail.get("subject") or ""), json.dumps(extra, ensure_ascii=False, default=str), text])
    return {
        "ada": ada,
        "official_url": document_url,
        "status": detail.get("status"),
        "privateData": detail.get("privateData"),
        "correctedVersionId": detail.get("correctedVersionId"),
        "organizationId": detail.get("organizationId"),
        "subject": " ".join(str(detail.get("subject") or "").split())[:800],
        "decisionTypeId": detail.get("decisionTypeId"),
        "issueDate": ms_iso(detail.get("issueDate")),
        "publishTimestamp": ms_iso(detail.get("publishTimestamp")),
        "protocolNumber": detail.get("protocolNumber"),
        "adam_tokens": sorted(set(match.group(0).upper() for match in ADAM_RE.finditer(joined))),
        "afm_tokens": sorted(set(AFM_RE.findall(joined)))[:50],
        "amount_mentions": sorted(set(match.group(1) for match in AMOUNT_RE.finditer(joined)))[:80],
        "matched_search_terms": [term for term in seed_terms if fold(term) in fold(joined)],
        "contexts": contexts(joined, seed_terms),
        "pdf_text_length": len(text),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "MizAI temporary official-source neighborhood validation/1.0"})
    output: dict[str, Any] = {"status": "completed", "executed_at": datetime.now(timezone.utc).isoformat(), "neighborhoods": {}}
    summary_lines = ["neighborhood\tada\tissue_date\tstatus\tsubject\tamounts\tafms\tadams\tmatched_terms\turl"]
    for name, seed_terms in NEIGHBORHOODS.items():
        by_ada: dict[str, dict[str, Any]] = {}
        source_terms: dict[str, set[str]] = defaultdict(set)
        for term in seed_terms:
            for record in search_term(session, term):
                ada = str(record.get("ada") or "")
                if not ada:
                    continue
                by_ada.setdefault(ada, record)
                source_terms[ada].add(term)
            time.sleep(0.4)
        inspected = []
        for ada, record in list(by_ada.items())[:60]:
            try:
                item = inspect(session, seed_terms, record)
                item["retrieved_by"] = sorted(source_terms[ada])
                inspected.append(item)
                summary_lines.append("\t".join([
                    name,
                    ada,
                    str(item.get("issueDate") or ""),
                    str(item.get("status") or ""),
                    str(item.get("subject") or "").replace("\t", " "),
                    ",".join(item.get("amount_mentions") or []),
                    ",".join(item.get("afm_tokens") or []),
                    ",".join(item.get("adam_tokens") or []),
                    ",".join(item.get("matched_search_terms") or []),
                    str(item.get("official_url") or ""),
                ]))
            except Exception as exc:
                inspected.append({"ada": ada, "error": type(exc).__name__, "message": str(exc)[:500]})
            time.sleep(0.35)
        output["neighborhoods"][name] = {
            "seed_terms": seed_terms,
            "search_record_count": len(by_ada),
            "records": inspected,
        }
    (OUT / "neighborhoods.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "subjects.tsv").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(json.dumps({name: value["search_record_count"] for name, value in output["neighborhoods"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
