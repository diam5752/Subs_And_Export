#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import requests

BASE = "https://diavgeia.gov.gr/luminapi/opendata/search"
QUERIES = [
    {"page": 0, "size": 5, "term": "μοναδική προσφορά", "from_issue_date": "2025-01-01", "to_issue_date": "2025-12-31"},
    {"page": 0, "size": 5, "term": "απευθείας ανάθεση", "from_issue_date": "2026-01-01", "to_issue_date": "2026-07-13"},
    {"page": 0, "size": 5, "term": "3ος ΑΠΕ", "from_issue_date": "2024-01-01", "to_issue_date": "2026-07-13"},
]

session = requests.Session()
session.headers.update({"Accept": "application/json", "User-Agent": "MizAI-Hunter-Probe/1.0"})
results = []
for params in QUERIES:
    item = {"params": params, "url": f"{BASE}?{urlencode(params)}"}
    try:
        response = session.get(BASE, params=params, timeout=(10, 45), allow_redirects=True)
        item.update({
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "final_url": response.url,
            "text_preview": response.text[:500],
        })
        try:
            payload = response.json()
            item["json_type"] = type(payload).__name__
            if isinstance(payload, dict):
                item["keys"] = sorted(payload.keys())
                decisions = payload.get("decisions")
                item["decisions_count"] = len(decisions) if isinstance(decisions, list) else None
                item["first_decision"] = decisions[0] if isinstance(decisions, list) and decisions else None
            else:
                item["json_preview"] = payload
        except Exception as exc:
            item["json_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}: {exc}"
    results.append(item)

out = Path("hunter-probe")
out.mkdir(parents=True, exist_ok=True)
(out / "probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
