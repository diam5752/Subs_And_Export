#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

BASE = "https://mizai.gr"
CASE_IDS = [
    "khmdhs-case-8e41d378652abb2f",
    "weekly-uoc-rethymno-cleaning-2026",
]
ENDPOINTS = [
    "/api/backend/api/cases/{case_id}",
    "/api/backend/api/cases/{case_id}/scores",
    "/api/backend/api/cases/{case_id}/ai-runs",
    "/api/backend/api/feed/{case_id}",
]


def compact(value: Any, depth: int = 0) -> Any:
    if depth > 10:
        return "<depth-limit>"
    if isinstance(value, dict):
        return {str(k): compact(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [compact(v, depth + 1) for v in value[:100]]
    if isinstance(value, str) and len(value) > 20000:
        return value[:20000] + "…"
    return value


def main() -> None:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "MizAI-public-case-validation/1.2",
        "Accept": "application/json",
    })
    result: dict[str, Any] = {}
    for case_id in CASE_IDS:
        entries: list[dict[str, Any]] = []
        for template in ENDPOINTS:
            path = template.format(case_id=case_id)
            url = BASE + path
            try:
                response = session.get(url, timeout=45, allow_redirects=True)
                entry: dict[str, Any] = {
                    "path": path,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "bytes": len(response.content),
                    "final_url": response.url,
                }
                try:
                    payload = response.json()
                    entry["json"] = compact(payload)
                except Exception:
                    entry["text_preview"] = response.text[:1000]
                entries.append(entry)
            except Exception as exc:
                entries.append({"path": path, "error": f"{type(exc).__name__}: {exc}"})
        result[case_id] = entries

    target = Path("case-fetch-output")
    target.mkdir(parents=True, exist_ok=True)
    (target / "case_api_compact.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
