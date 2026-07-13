#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "https://mizai.gr"
CASE_IDS = [
    "khmdhs-case-8e41d378652abb2f",
    "weekly-uoc-rethymno-cleaning-2026",
]
PATHS = [
    "/cases/{case_id}",
    "/api/backend/api/cases/{case_id}",
    "/api/backend/api/feed/{case_id}",
    "/api/cases/{case_id}",
    "/api/feed/{case_id}",
]


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "MizAI-public-case-validation/1.0", "Accept": "application/json,text/html"})
    out: dict[str, object] = {}
    for case_id in CASE_IDS:
        case_out: dict[str, object] = {}
        for template in PATHS:
            path = template.format(case_id=case_id)
            url = BASE + path
            try:
                response = session.get(url, timeout=45, allow_redirects=True)
                content_type = response.headers.get("content-type", "")
                entry: dict[str, object] = {
                    "status": response.status_code,
                    "final_url": response.url,
                    "content_type": content_type,
                    "bytes": len(response.content),
                }
                if "application/json" in content_type:
                    try:
                        entry["body"] = response.json()
                    except Exception:
                        entry["body_text"] = response.text[:20000]
                else:
                    entry["body_text"] = response.text[:50000]
                case_out[path] = entry
            except Exception as exc:
                case_out[path] = {"error": f"{type(exc).__name__}: {exc}"}
        out[case_id] = case_out

    target = Path("case-fetch-output")
    target.mkdir(parents=True, exist_ok=True)
    (target / "case_details.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
