#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path("candidate-inspection-output")
SOURCE = ROOT / "inspection.json"


def trim(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    condensed: dict[str, Any] = {"status": payload.get("status"), "groups": {}}
    subject_lines = ["group\tada\tissue_date\tpublish_date\tstatus\tcorrected\tsubject\tamounts\tafms\tadams\turl"]
    for group_name, raw_items in (payload.get("groups") or {}).items():
        items = [item for item in raw_items if isinstance(item, dict)]
        keyword_counts: Counter[str] = Counter()
        decisions = []
        fact_lines = [f"GROUP\t{group_name}\tCOUNT\t{len(items)}"]
        for item in items:
            excerpts = []
            compact_matches = []
            for excerpt in list(item.get("keyword_excerpts") or []):
                if not isinstance(excerpt, dict):
                    continue
                keyword = str(excerpt.get("keyword") or "")
                keyword_counts[keyword] += 1
                if len(excerpts) < 4:
                    excerpts.append({
                        "keyword": keyword,
                        "excerpt": trim(excerpt.get("excerpt"), 900),
                    })
                if len(compact_matches) < 3 and keyword not in {value.split("=", 1)[0] for value in compact_matches}:
                    compact_matches.append(f"{keyword}={trim(excerpt.get('excerpt'), 320)}")
            extra = item.get("extraFieldValues") if isinstance(item.get("extraFieldValues"), dict) else {}
            decision = {
                "ada": item.get("ada"),
                "official_url": item.get("documentUrl"),
                "status": item.get("status"),
                "privateData": item.get("privateData"),
                "correctedVersionId": item.get("correctedVersionId"),
                "organizationId": item.get("organizationId"),
                "subject": trim(item.get("subject"), 700),
                "decisionTypeId": item.get("decisionTypeId"),
                "issueDate": item.get("issueDate"),
                "publishTimestamp": item.get("publishTimestamp"),
                "protocolNumber": item.get("protocolNumber"),
                "adam_tokens": list(item.get("adam_tokens") or [])[:20],
                "contract_refs": list(item.get("contract_refs") or [])[:20],
                "amount_mentions": list(item.get("amount_mentions") or [])[:20],
                "afm_mentions": list(item.get("afm_mentions") or [])[:20],
                "extra_field_keys": sorted(extra.keys()),
                "pdf_text_length": item.get("pdf_text_length"),
                "keyword_excerpts": excerpts,
                "text_preview": trim(item.get("text_preview"), 1800),
                "error": item.get("error"),
            }
            decisions.append(decision)
            fact_lines.append("\t".join([
                "DECISION",
                str(decision.get("ada") or ""),
                str(decision.get("issueDate") or ""),
                str(decision.get("publishTimestamp") or ""),
                "STATUS=" + str(decision.get("status") or ""),
                "CORRECTED=" + str(decision.get("correctedVersionId") or ""),
                "SUBJECT=" + trim(decision.get("subject"), 600),
                "AMOUNTS=" + ",".join(decision.get("amount_mentions") or []),
                "AFMS=" + ",".join(decision.get("afm_mentions") or []),
                "ADAMS=" + ",".join(decision.get("adam_tokens") or []),
                "MATCHES=" + " || ".join(compact_matches),
                "URL=" + str(decision.get("official_url") or ""),
            ]))
            subject_lines.append("\t".join([
                group_name,
                str(decision.get("ada") or ""),
                str(decision.get("issueDate") or ""),
                str(decision.get("publishTimestamp") or ""),
                str(decision.get("status") or ""),
                str(decision.get("correctedVersionId") or ""),
                trim(decision.get("subject"), 500),
                ",".join(decision.get("amount_mentions") or []),
                ",".join(decision.get("afm_mentions") or []),
                ",".join(decision.get("adam_tokens") or []),
                str(decision.get("official_url") or ""),
            ]))
        condensed["groups"][group_name] = {
            "decision_count": len(decisions),
            "organization_ids": sorted({str(item.get("organizationId")) for item in items if item.get("organizationId")}),
            "unique_adams": sorted({token for item in items for token in list(item.get("adam_tokens") or [])}),
            "unique_contract_refs": sorted({token for item in items for token in list(item.get("contract_refs") or [])})[:80],
            "keyword_document_counts": dict(keyword_counts.most_common()),
            "decisions": decisions,
        }
        (ROOT / f"{group_name}.facts.txt").write_text("\n".join(fact_lines) + "\n", encoding="utf-8")
    (ROOT / "subjects.tsv").write_text("\n".join(subject_lines) + "\n", encoding="utf-8")
    (ROOT / "condensed.json").write_text(json.dumps(condensed, ensure_ascii=False, indent=2), encoding="utf-8")
    for group_name, value in condensed["groups"].items():
        (ROOT / f"{group_name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["decision_count"] for name, value in condensed["groups"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
