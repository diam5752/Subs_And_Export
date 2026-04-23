#!/usr/bin/env python3

from __future__ import annotations

import json
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "testdata" / "subtitles" / "greek_long_cue.json"
sys.path.insert(0, str(REPO_ROOT))


def run_once(tmp_path: Path) -> float:
    from backend.app.services.subtitle_exports import export_subtitle_file

    start = time.perf_counter()
    export_subtitle_file(
        transcription_json=FIXTURE,
        export_path=tmp_path / "processed.srt",
        export_format="srt",
        max_subtitle_lines=2,
        subtitle_size=85,
    )
    return time.perf_counter() - start


def main() -> int:
    logging.disable(logging.INFO)

    if not FIXTURE.exists():
        print(f"ERROR: missing performance fixture {FIXTURE.relative_to(REPO_ROOT)}")
        return 1

    timings: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for _ in range(7):
            timings.append(run_once(tmp_path))

    median_ms = statistics.median(timings) * 1000
    max_ms = max(timings) * 1000
    budget_median_ms = 75.0
    budget_max_ms = 250.0

    print(
        json.dumps(
            {
                "gate": "subtitle-export-performance-smoke",
                "median_ms": round(median_ms, 3),
                "max_ms": round(max_ms, 3),
                "budget_median_ms": budget_median_ms,
                "budget_max_ms": budget_max_ms,
            },
            indent=2,
        )
    )

    if median_ms > budget_median_ms or max_ms > budget_max_ms:
        print("FAIL: subtitle export performance smoke exceeded its budget")
        return 1

    print("PASS: subtitle export performance smoke is within budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
