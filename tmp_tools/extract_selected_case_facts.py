#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path("selected-case-facts")
ROOT.mkdir(parents=True, exist_ok=True)

SELECTED = {
    "ippokrateio": {
        "6996469067-ΡΔ2",
        "ΨΓ6Ζ469067-1ΩΓ",
        "ΨΒΑ0469067-ΗΑ9",
        "9ΛΥ8469067-Δ9Ω",
        "ΡΠΣΕ469067-ΨΞ8",
        "66ΒΡ469067-ΓΧΤ",
    },
    "oak": {
        "ΨΖΝ5ΟΞ5Ψ-Δ9Ο",
        "61Ξ6ΟΞ5Ψ-Χ5Β",
        "9ΧΧΜΟΞ5Ψ-ΘΜΒ",
        "ΡΒ8ΡΟΞ5Ψ-ΗΤ7",
        "ΨΓ15ΟΞ5Ψ-02Μ",
        "9ΧΞΞΟΞ5Ψ-347",
        "ΕΧΗ6ΟΞ5Ψ-4ΤΥ",
    },
}


def compact(value: Any, limit: int = 1400) -> str:
    return " ".join(str(value or "").split())[:limit]


def add_item(bucket: dict[str, dict[str, Any]], item: dict[str, Any], source: str) -> None:
    ada = str(item.get("ada") or "")
    if not ada:
        return
    target = "ippokrateio" if ada in SELECTED["ippokrateio"] else "oak" if ada in SELECTED["oak"] else None
    if target is None:
        return
    current = bucket[target].setdefault(ada, {"ada": ada, "sources": []})
    if source not in current["sources"]:
        current["sources"].append(source)
    for key in (
        "official_url", "status", "privateData", "correctedVersionId", "organizationId",
        "subject", "decisionTypeId", "issueDate", "publishTimestamp", "protocolNumber",
        "adam_tokens", "afm_tokens", "afm_mentions", "amount_mentions", "pdf_text_length",
        "matched_search_terms", "retrieved_by",
    ):
        value = item.get(key)
        if value not in (None, "", [], {}):
            current[key] = value
    context_rows = item.get("contexts") or item.get("keyword_excerpts") or []
    contexts = current.setdefault("contexts", [])
    seen = {compact(row.get("excerpt"), 500) for row in contexts if isinstance(row, dict)}
    for row in context_rows:
        if not isinstance(row, dict):
            continue
        excerpt = compact(row.get("excerpt"), 1500)
        if not excerpt or compact(excerpt, 500) in seen:
            continue
        contexts.append({
            "term": str(row.get("term") or row.get("keyword") or ""),
            "excerpt": excerpt,
        })
        seen.add(compact(excerpt, 500))
        if len(contexts) >= 16:
            break


def main() -> None:
    bucket: dict[str, dict[str, Any]] = {"ippokrateio": {}, "oak": {}}
    inspection_path = Path("candidate-inspection-output/inspection.json")
    if inspection_path.exists():
        inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
        for group, items in (inspection.get("groups") or {}).items():
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    add_item(bucket, item, f"inspection:{group}")
    neighborhoods_path = Path("candidate-neighborhood-output/neighborhoods.json")
    if neighborhoods_path.exists():
        neighborhoods = json.loads(neighborhoods_path.read_text(encoding="utf-8"))
        for name, payload in (neighborhoods.get("neighborhoods") or {}).items():
            if not isinstance(payload, dict):
                continue
            for item in payload.get("records") or []:
                if isinstance(item, dict):
                    add_item(bucket, item, f"neighborhood:{name}")

    for case_name, items in bucket.items():
        ordered = [items[ada] for ada in sorted(items)]
        (ROOT / f"{case_name}.json").write_text(
            json.dumps({"case": case_name, "records": ordered}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = [f"CASE\t{case_name}\tRECORDS\t{len(ordered)}"]
        for item in ordered:
            lines.append("\t".join([
                "RECORD",
                item["ada"],
                str(item.get("issueDate") or ""),
                "SUBJECT=" + compact(item.get("subject"), 800),
                "AMOUNTS=" + ",".join(item.get("amount_mentions") or []),
                "AFMS=" + ",".join(item.get("afm_tokens") or item.get("afm_mentions") or []),
                "ADAMS=" + ",".join(item.get("adam_tokens") or []),
                "URL=" + str(item.get("official_url") or ""),
            ]))
            for row in item.get("contexts") or []:
                lines.append("\t".join([
                    "CONTEXT",
                    item["ada"],
                    str(row.get("term") or ""),
                    compact(row.get("excerpt"), 1400),
                ]))
        (ROOT / f"{case_name}.facts.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({name: len(items) for name, items in bucket.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
