#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lizard

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".codex" / "code-complexity-baseline.json"
SOURCE_PATHS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "main.py",
    REPO_ROOT / "backend" / "cli.py",
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "src" / "main" / "java",
    REPO_ROOT / ".codex" / "scripts",
)
SUPPORTED_SUFFIXES = frozenset({".java", ".js", ".jsx", ".py", ".ts", ".tsx"})
EXCLUDED_PARTS = frozenset({"__mocks__", "__tests__", "tests"})
LIMITS = {
    "cyclomatic_complexity": 10,
    "nloc": 50,
}
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    name: str
    start_line: int
    cyclomatic_complexity: int
    nloc: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.name}"


@dataclass(frozen=True)
class Comparison:
    regressions: tuple[str, ...]
    stale_entries: tuple[str, ...]

    @property
    def is_exact(self) -> bool:
        return not self.regressions and not self.stale_entries


def source_files(source_paths: Sequence[Path] = SOURCE_PATHS) -> list[Path]:
    files: set[Path] = set()
    for source_path in source_paths:
        candidates = [source_path] if source_path.is_file() else source_path.rglob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix not in SUPPORTED_SUFFIXES:
                continue
            relative = candidate.relative_to(REPO_ROOT)
            if EXCLUDED_PARTS.intersection(relative.parts):
                continue
            if candidate.name.endswith((".test.js", ".test.jsx", ".test.ts", ".test.tsx")):
                continue
            files.add(candidate)
    return sorted(files)


def collect_metrics(paths: Sequence[Path] | None = None) -> list[FunctionMetric]:
    metrics: list[FunctionMetric] = []
    for path in source_files() if paths is None else paths:
        analysis: Any = lizard.analyze_file(str(path))
        relative = str(path.relative_to(REPO_ROOT))
        for function in analysis.function_list:
            metrics.append(
                FunctionMetric(
                    path=relative,
                    name=str(function.name),
                    start_line=int(function.start_line),
                    cyclomatic_complexity=int(function.cyclomatic_complexity),
                    nloc=int(function.nloc),
                )
            )
    return metrics


def grouped_hotspots(
    metrics: Sequence[FunctionMetric],
    limits: Mapping[str, int] = LIMITS,
) -> dict[str, dict[str, list[int]]]:
    grouped: dict[str, dict[str, list[int]]] = {}
    for metric_name, limit in limits.items():
        values: defaultdict[str, list[int]] = defaultdict(list)
        for function in metrics:
            value = int(getattr(function, metric_name))
            if value > limit:
                values[function.key].append(value)
        grouped[metric_name] = {key: sorted(scores, reverse=True) for key, scores in sorted(values.items())}
    return grouped


def compare_hotspots(
    baseline: Mapping[str, Mapping[str, Sequence[int]]],
    current: Mapping[str, Mapping[str, Sequence[int]]],
    limits: Mapping[str, int] = LIMITS,
) -> Comparison:
    regressions: list[str] = []
    stale_entries: list[str] = []

    for metric_name, limit in limits.items():
        baseline_metric = baseline.get(metric_name, {})
        current_metric = current.get(metric_name, {})
        for key in sorted(set(baseline_metric) | set(current_metric)):
            allowed = sorted((int(value) for value in baseline_metric.get(key, ())), reverse=True)
            observed = sorted((int(value) for value in current_metric.get(key, ())), reverse=True)
            key_regressions = score_regressions(metric_name, key, limit, allowed, observed)
            regressions.extend(key_regressions)
            if observed != allowed and not key_regressions:
                stale_entries.append(
                    f"{metric_name}: {key} improved from {allowed or [limit]} to {observed or [limit]}"
                )

    return Comparison(tuple(regressions), tuple(stale_entries))


def score_regressions(
    metric_name: str,
    key: str,
    limit: int,
    allowed: Sequence[int],
    observed: Sequence[int],
) -> list[str]:
    regressions: list[str] = []
    for index, score in enumerate(observed):
        ceiling = allowed[index] if index < len(allowed) else limit
        if score > ceiling:
            regressions.append(f"{metric_name}: {key} score {score} exceeds allowed {ceiling}")
    return regressions


def baseline_document(hotspots: Mapping[str, Mapping[str, Sequence[int]]]) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {
            "name": "lizard",
            "version": importlib.metadata.version("lizard"),
        },
        "limits": LIMITS,
        "source_paths": [str(path.relative_to(REPO_ROOT)) for path in SOURCE_PATHS],
        "hotspots": hotspots,
    }


def read_json_object(path: Path) -> dict[str, object]:
    try:
        raw_document: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exception:
        raise ValueError(f"Complexity baseline is missing: {path.relative_to(REPO_ROOT)}") from exception
    except json.JSONDecodeError as exception:
        raise ValueError(f"Complexity baseline is not valid JSON: {exception}") from exception

    if not isinstance(raw_document, dict):
        raise ValueError("Complexity baseline root must be an object")
    return {str(key): value for key, value in raw_document.items()}


def validate_baseline(document: Mapping[str, object]) -> None:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Complexity baseline schema version is unsupported")
    if document.get("limits") != LIMITS:
        raise ValueError("Complexity baseline limits do not match the enforced limits")
    tool = document.get("tool")
    installed_version = importlib.metadata.version("lizard")
    if not isinstance(tool, dict) or tool.get("name") != "lizard" or tool.get("version") != installed_version:
        raise ValueError(f"Complexity baseline requires lizard {installed_version}")
    hotspots = document.get("hotspots")
    if not isinstance(hotspots, dict):
        raise ValueError("Complexity baseline has no hotspot map")


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, object]:
    document = read_json_object(path)
    validate_baseline(document)
    return document


def write_baseline(
    hotspots: Mapping[str, Mapping[str, Sequence[int]]],
    path: Path = BASELINE_PATH,
) -> None:
    document = baseline_document(hotspots)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail on new or worsened cyclomatic-complexity and function-size hotspots.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Record improvements; refuses to bless any regression.",
    )
    return parser.parse_args(arguments)


def hotspot_count(hotspots: Mapping[str, Mapping[str, Sequence[int]]], metric_name: str) -> int:
    return sum(len(scores) for scores in hotspots.get(metric_name, {}).values())


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    current = grouped_hotspots(collect_metrics())

    if not BASELINE_PATH.exists():
        if not args.update_baseline:
            print("FAIL: complexity baseline is missing; bootstrap it with --update-baseline.", file=sys.stderr)
            return 2
        write_baseline(current)
        print(f"WROTE: {BASELINE_PATH.relative_to(REPO_ROOT)}")
        return 0

    try:
        document = load_baseline()
    except ValueError as exception:
        print(f"FAIL: {exception}", file=sys.stderr)
        return 2

    baseline = document["hotspots"]
    if not isinstance(baseline, dict):
        print("FAIL: complexity baseline hotspot map is invalid", file=sys.stderr)
        return 2
    comparison = compare_hotspots(baseline, current)

    if comparison.regressions:
        print("FAIL: code complexity regressed:", file=sys.stderr)
        for item in comparison.regressions:
            print(f"- {item}", file=sys.stderr)
        return 1

    if args.update_baseline:
        write_baseline(current)
        print(f"WROTE: {BASELINE_PATH.relative_to(REPO_ROOT)}")
        return 0

    if comparison.stale_entries:
        print("FAIL: complexity improved; ratchet the reviewed baseline:", file=sys.stderr)
        for item in comparison.stale_entries:
            print(f"- {item}", file=sys.stderr)
        print("Run: python3 .codex/scripts/check_code_complexity.py --update-baseline", file=sys.stderr)
        return 1

    print(
        "PASS: code complexity ratchet held "
        f"({hotspot_count(current, 'cyclomatic_complexity')} complexity and "
        f"{hotspot_count(current, 'nloc')} function-size legacy hotspots; "
        f"new limits are complexity <= {LIMITS['cyclomatic_complexity']} and "
        f"NLOC <= {LIMITS['nloc']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
