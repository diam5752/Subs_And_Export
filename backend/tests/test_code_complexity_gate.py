from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPLEXITY_GATE_PATH = REPOSITORY_ROOT / ".codex" / "scripts" / "check_code_complexity.py"


def load_complexity_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_code_complexity", COMPLEXITY_GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load code-complexity gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def metric(
    gate: ModuleType,
    *,
    path: str = "backend/app/example.py",
    name: str = "handler",
    complexity: int = 11,
    nloc: int = 51,
) -> Any:
    return gate.FunctionMetric(
        path=path,
        name=name,
        start_line=10,
        cyclomatic_complexity=complexity,
        nloc=nloc,
    )


def test_complexity_gate_groups_only_scores_above_the_hard_limits() -> None:
    gate = load_complexity_gate()

    grouped = gate.grouped_hotspots(
        [
            metric(gate, complexity=10, nloc=50),
            metric(gate, complexity=12, nloc=55),
            metric(gate, complexity=18, nloc=45),
        ]
    )

    assert grouped == {
        "cyclomatic_complexity": {"backend/app/example.py::handler": [18, 12]},
        "nloc": {"backend/app/example.py::handler": [55]},
    }


def test_complexity_gate_rejects_new_and_worsened_hotspots() -> None:
    gate = load_complexity_gate()
    baseline = {
        "cyclomatic_complexity": {"backend/app/example.py::handler": [14]},
        "nloc": {},
    }
    current = {
        "cyclomatic_complexity": {
            "backend/app/example.py::handler": [15],
            "frontend/src/new.ts::newHandler": [11],
        },
        "nloc": {},
    }

    comparison = gate.compare_hotspots(baseline, current)

    assert comparison.stale_entries == ()
    assert comparison.regressions == (
        "cyclomatic_complexity: backend/app/example.py::handler score 15 exceeds allowed 14",
        "cyclomatic_complexity: frontend/src/new.ts::newHandler score 11 exceeds allowed 10",
    )


def test_complexity_gate_requires_baseline_ratchet_after_improvement() -> None:
    gate = load_complexity_gate()
    baseline = {
        "cyclomatic_complexity": {"backend/app/example.py::handler": [18, 14]},
        "nloc": {"backend/app/example.py::handler": [70]},
    }
    current = {
        "cyclomatic_complexity": {"backend/app/example.py::handler": [16]},
        "nloc": {},
    }

    comparison = gate.compare_hotspots(baseline, current)

    assert comparison.regressions == ()
    assert comparison.stale_entries == (
        "cyclomatic_complexity: backend/app/example.py::handler improved from [18, 14] to [16]",
        "nloc: backend/app/example.py::handler improved from [70] to [50]",
    )


def test_checked_in_complexity_baseline_matches_the_current_sources() -> None:
    gate = load_complexity_gate()

    assert gate.main([]) == 0
