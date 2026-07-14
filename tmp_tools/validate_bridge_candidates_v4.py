#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://diavgeia.gov.gr"
DETAIL = BASE + "/luminapi/api/decisions/{ada}"
DOC = BASE + "/doc/{ada}"
MODE = os.environ["VALIDATION_MODE"]
OUT = Path(os.environ["VALIDATION_OUT"])

CASES = {
    "cleaning": {
        "adas": ("ΡΞ5ΛΟΡΕΠ-ΒΣΦ", "ΨΜ9ΚΟΡΕΠ-Γ6Φ"),
        "expected_object": ("καθαρισμ", "90910000-9"),
        "expected_supplier": ("ipirotiki facility services",),
        "minimum_chains": 2,
        "minimum_total_gross": 350000.0,
    },
    "medical_waste": {
        "adas": ("6Δ8Σ46906Π-ΟΕΟ", "Ρ7ΚΔ46906Π-Ν7Κ", "ΨΙΤΨ46906Π-ΛΣ2", "ΨΟΜΣ46906Π-Ι6Λ"),
        "expected_object": ("ιατρικων αποβλητων", "90524000-6"),
        "expected_supplier": ("αποτεφρωτηρασ", "ecoster"),
        "minimum_chains": 4,
        "minimum_total_gross": 440000.0,
    },
}

DATE_RANGE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*(?:έως|ως|μέχρι|-)\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})", re.I)
PROC_ADAM = re.compile(r"\b\d{2}PROC\d{9}\b", re.I)
NEGOTIATION_ID = re.compile(r"(?:ΔΙΑΠΡ(?:Α|Γ)ΜΑΤΕΥΣΗ|διαπραγμάτευση)\s*(\d{1,3}/20\d{2})", re.I)
GROSS_SUBJECT = re.compile(r"(?:ήτοι|συνολικού προϋπολογισμού)\s*([\d.]+,\d{2})\s*€?\s*(?:με|συμπεριλαμβανομένου)?\s*Φ", re.I)
MONEY_GROSS = re.compile(r"([\d.]+,\d{2})\s*€[^\n]{0,80}(?:με Φ\.?Π\.?Α|συμπ/νου ΦΠΑ|συμπεριλαμβανομένου ΦΠΑ)", re.I)
NET_VAT = re.compile(r"([\d.]+,\d{2})\s*€?\s*(?:μη συμπεριλαμβανομένου|χωρίς|πλέον)\s*Φ\.?Π\.?Α\.?\s*(\d{1,2})\s*%", re.I)


def fold(value: str) -> str:
    raw = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join("".join(ch for ch in raw if unicodedata.category(ch) != "Mn").split())


def money(raw: str) -> float:
    return float(raw.replace(".", "").replace(",", "."))


def request(session: requests.Session, url: str, timeout: int = 60) -> requests.Response:
    last = None
    for attempt in range(5):
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
    with tempfile.TemporaryDirectory(prefix="bridge-v4-") as tmp:
        pdf = Path(tmp) / "doc.pdf"
        txt = Path(tmp) / "doc.txt"
        pdf.write_bytes(content)
        done = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), str(txt)], capture_output=True, timeout=75, check=False)
        return txt.read_text(encoding="utf-8", errors="replace")[:350000] if done.returncode == 0 and txt.exists() else ""


def parse_date_ms(value) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def gross_amount(subject: str, text: str) -> tuple[float | None, str]:
    for source, value in (("subject", subject), ("pdf", text[:25000])):
        matches = [money(match.group(1)) for match in MONEY_GROSS.finditer(value)]
        if matches:
            plausible = [amount for amount in matches if 1000 <= amount <= 5000000]
            if plausible:
                return max(plausible), f"explicit_gross_{source}"
    for value in (subject, text[:25000]):
        match = NET_VAT.search(value)
        if match:
            net = money(match.group(1))
            vat = int(match.group(2))
            return round(net * (1 + vat / 100), 2), "computed_from_explicit_net_and_vat"
    return None, "missing"


def service_period(subject: str, text: str) -> tuple[str | None, str | None]:
    for value in (subject, text[:15000]):
        match = DATE_RANGE.search(value)
        if not match:
            continue
        d1, m1, y1, d2, m2, y2 = map(int, match.groups())
        try:
            return date(y1, m1, d1).isoformat(), date(y2, m2, d2).isoformat()
        except ValueError:
            continue
    return None, None


def chain_identifier(subject: str, text: str) -> tuple[str, str]:
    adams = PROC_ADAM.findall(subject + "\n" + text[:20000])
    if adams:
        return adams[0].upper(), "PROC_ADAM"
    match = NEGOTIATION_ID.search(subject + "\n" + text[:6000])
    if match:
        return match.group(1), "negotiation_number"
    return "", "missing"


def supplier_confirmed(subject: str, text: str, terms: tuple[str, ...]) -> tuple[bool, str]:
    value = fold(subject + "\n" + text[:18000])
    hits = [term for term in terms if fold(term) in value]
    return len(hits) == len(terms), ", ".join(hits)


def object_confirmed(subject: str, text: str, terms: tuple[str, ...]) -> bool:
    value = fold(subject + "\n" + text[:10000])
    return all(fold(term) in value for term in terms)


def procedure_facts(subject: str, text: str) -> dict:
    value = fold(subject + "\n" + text[:25000])
    without_publication = "χωρισ προηγουμενη δημοσιευση" in value
    article_32_emergency = (
        ("αρθρο 32" in value or "αρ. 32" in value)
        and any(term in value for term in ("κατεπειγουσα αναγκη", "απροβλεπτη περισταση", "παρ.2 περ.γ", "παρ 2 περ γ"))
    )
    lowest_price = any(term in value for term in ("χαμηλοτερη προσφορα", "μονο βασει τιμησ", "στο μειοδοτη"))
    open_or_pending = any(term in value for term in ("ανοικτοσ διαγωνισμοσ", "ανοικτου διαγωνισμου", "νεα διαγωνιστικη διαδικασια", "εκκρεμη διαγωνιστικη"))
    return {
        "without_publication": without_publication,
        "article_32_emergency": article_32_emergency,
        "lowest_price": lowest_price,
        "open_or_pending_tender": open_or_pending,
    }


def main() -> None:
    config = CASES[MODE]
    session = requests.Session()
    session.headers.update({"User-Agent": "MizAI strict bridge candidate validation v4/1.0", "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.1"})
    records = []
    failures = []
    for ada in config["adas"]:
        try:
            detail_response = request(session, DETAIL.format(ada=quote(ada, safe="")))
            if not detail_response.ok:
                raise RuntimeError(f"detail HTTP {detail_response.status_code}")
            detail = detail_response.json()
            document_url = str(detail.get("documentUrl") or DOC.format(ada=quote(ada, safe="")))
            pdf_response = request(session, document_url, timeout=75)
            if not pdf_response.ok or "pdf" not in pdf_response.headers.get("content-type", "").casefold():
                raise RuntimeError(f"PDF HTTP/content-type {pdf_response.status_code} {pdf_response.headers.get('content-type')}")
            text = pdf_text(pdf_response.content)
            subject = " ".join(str(detail.get("subject") or "").split())
            amount, amount_basis = gross_amount(subject, text)
            start, end = service_period(subject, text)
            chain_id, chain_basis = chain_identifier(subject, text)
            supplier_ok, supplier_evidence = supplier_confirmed(subject, text, config["expected_supplier"])
            procedures = procedure_facts(subject, text)
            status_ok = str(detail.get("status") or "") == "PUBLISHED" and not detail.get("correctedVersionId") and detail.get("privateData") is not True
            records.append({
                "ada": ada,
                "official_url": document_url,
                "subject": subject,
                "issue_date": parse_date_ms(detail.get("issueDate")),
                "status_current_public": status_ok,
                "object_confirmed": object_confirmed(subject, text, config["expected_object"]),
                "supplier_confirmed": supplier_ok,
                "supplier_evidence": supplier_evidence,
                "chain_id": chain_id,
                "chain_id_basis": chain_basis,
                "gross_amount_eur": amount,
                "gross_amount_basis": amount_basis,
                "service_start": start,
                "service_end": end,
                **procedures,
            })
        except Exception as exc:
            failures.append({"ada": ada, "error": type(exc).__name__, "message": str(exc)[:300]})

    unique_chain_ids = {record["chain_id"] for record in records if record["chain_id"]}
    current_ok = len(records) == len(config["adas"]) and all(record["status_current_public"] for record in records)
    object_ok = all(record["object_confirmed"] for record in records)
    supplier_ok = all(record["supplier_confirmed"] for record in records)
    chain_ok = len(unique_chain_ids) >= config["minimum_chains"]
    exceptional_ok = all(record["without_publication"] or record["article_32_emergency"] for record in records)
    amounts = [record["gross_amount_eur"] for record in records if record["gross_amount_eur"] is not None]
    amount_total = round(sum(amounts), 2)
    materiality_ok = len(amounts) == len(records) and amount_total >= config["minimum_total_gross"]

    periods = [(record["service_start"], record["service_end"]) for record in records if record["service_start"] and record["service_end"]]
    temporal_ok = False
    if MODE == "cleaning" and len(periods) == len(records):
        ordered = sorted((date.fromisoformat(start), date.fromisoformat(end)) for start, end in periods)
        temporal_ok = all((ordered[index + 1][0] - ordered[index][1]).days in {0, 1} for index in range(len(ordered) - 1))
    elif MODE == "medical_waste":
        dates = sorted(date.fromisoformat(record["issue_date"]) for record in records if record["issue_date"])
        temporal_ok = len(dates) == len(records) and (dates[-1] - dates[0]).days >= 90

    families = []
    if exceptional_ok and chain_ok:
        families.append("repeated_exceptional_procedure")
    if supplier_ok and chain_ok:
        families.append("same_supplier_distinct_chains")
    if temporal_ok:
        families.append("temporal_continuity")
    if materiality_ok:
        families.append("materiality")

    evidence_quality = 30 if current_ok and object_ok and supplier_ok and chain_ok and materiality_ok else 22
    pattern_strength = 25 if chain_ok and exceptional_ok and temporal_ok else 16
    peer_deviation = 17 if exceptional_ok and len(records) >= 3 else 14 if exceptional_ok else 0
    materiality = 10 if amount_total >= 350000 else 8 if amount_total >= 150000 else 4
    ordinary_explanations = []
    if any(record["open_or_pending_tender"] for record in records):
        ordinary_explanations.append("Υπάρχει ανοικτός ή εκκρεμής διαγωνισμός.")
    if all(record["lowest_price"] for record in records):
        ordinary_explanations.append("Το κριτήριο αναφέρει χαμηλότερη τιμή.")
    ordinary_explanations.append("Η υπηρεσία είναι κρίσιμη για συνεχή λειτουργία νοσοκομειακής δομής.")
    falsification_survival = 12 if len(records) >= 3 else 11
    if len(ordinary_explanations) >= 3:
        falsification_survival -= 2
    score = evidence_quality + pattern_strength + peer_deviation + materiality + falsification_survival
    score = min(100, max(0, score))
    caps = []
    independent_risk_families = [family for family in families if family != "materiality"]
    if len(independent_risk_families) < 2:
        caps.append("λιγότερες από δύο ανεξάρτητες evidence families")
        score = min(score, 69)
    if not all((current_ok, object_ok, supplier_ok, chain_ok, exceptional_ok, materiality_ok, temporal_ok)):
        caps.append("δεν πέρασαν όλα τα αυστηρά validation gates")
        score = min(score, 69)

    result = {
        "status": "FOUND_VALIDATED" if score >= 80 and not caps else "RESEARCH_LEAD",
        "mode": MODE,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "review_priority": score,
        "not_a_probability_of_illegality": True,
        "families": independent_risk_families,
        "materiality_fact": "materiality" in families,
        "gates": {
            "current_public_records": current_ok,
            "same_object": object_ok,
            "same_supplier": supplier_ok,
            "distinct_chain_identity": chain_ok,
            "exceptional_procedure_each_chain": exceptional_ok,
            "typed_gross_amount_each_chain": materiality_ok,
            "temporal_pattern": temporal_ok,
        },
        "score_axes": {
            "evidence_quality": evidence_quality,
            "pattern_strength": pattern_strength,
            "peer_deviation": peer_deviation,
            "materiality": materiality,
            "falsification_survival": falsification_survival,
        },
        "caps": caps,
        "known_gross_total_eur": amount_total,
        "ordinary_explanations": ordinary_explanations,
        "records": records,
        "failures": failures,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "FOUND_VALIDATED":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
