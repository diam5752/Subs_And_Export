#!/usr/bin/env python3

"""Enforce independent line and branch thresholds from Coverage.py JSON."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast


def percentage(covered: int, total: int, metric: str) -> float:
    if total <= 0:
        raise ValueError(f"coverage report has no {metric} to evaluate")
    if covered < 0 or covered > total:
        raise ValueError(f"coverage report has invalid {metric} totals")
    return covered * 100.0 / total


def integer_total(totals: dict[str, object], key: str) -> int:
    value = totals.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"coverage report is missing integer total `{key}`")
    return value


def coverage_percentages(report: dict[str, object]) -> tuple[float, float]:
    raw_totals = report.get("totals")
    if not isinstance(raw_totals, dict):
        raise ValueError("coverage report is missing `totals`")
    totals = cast(dict[str, object], raw_totals)
    line_pct = percentage(
        integer_total(totals, "covered_lines"),
        integer_total(totals, "num_statements"),
        "executable lines",
    )
    branch_pct = percentage(
        integer_total(totals, "covered_branches"),
        integer_total(totals, "num_branches"),
        "branches",
    )
    return line_pct, branch_pct


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Require independent minimum line and branch coverage.",
    )
    parser.add_argument("report", type=Path, help="Coverage.py JSON report")
    parser.add_argument("--lines", type=float, default=90.0, help="minimum line percentage")
    parser.add_argument("--branches", type=float, default=80.0, help="minimum branch percentage")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw_report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(raw_report, dict):
            raise ValueError("coverage report root must be an object")
        line_pct, branch_pct = coverage_percentages(cast(dict[str, object], raw_report))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: unable to evaluate coverage: {error}", file=sys.stderr)
        return 2

    checks = (
        ("lines", line_pct, args.lines),
        ("branches", branch_pct, args.branches),
    )
    failures = [(name, actual, minimum) for name, actual, minimum in checks if actual < minimum]
    rendered = ", ".join(f"{name} {actual:.2f}% (minimum {minimum:.2f}%)" for name, actual, minimum in checks)
    if failures:
        print(f"FAIL: coverage threshold missed: {rendered}", file=sys.stderr)
        return 1

    print(f"PASS: coverage thresholds met: {rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
