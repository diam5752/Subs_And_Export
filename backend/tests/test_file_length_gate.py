from __future__ import annotations

import importlib.util
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType, SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FILE_LENGTH_GATE_PATH = REPOSITORY_ROOT / ".codex" / "scripts" / "check_file_length.py"


def load_file_length_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_file_length", FILE_LENGTH_GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load file-length gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_file_length_gate_targets_hand_written_code_without_generated_data() -> None:
    gate = load_file_length_gate()

    included = [
        "Dockerfile",
        "Caddyfile",
        "deploy/Caddyfile.production",
        "Makefile",
        ".github/workflows/quality-gates.yml",
        "backend/app/main.py",
        "backend/alembic/script.py.mako",
        "deploy/verify.sh",
        "frontend/eslint.config.mjs",
        "frontend/src/app/page.tsx",
        "frontend/src/app/globals.css",
        "pom.xml",
        "native/Editor.swift",
        "infrastructure/main.tf",
        "src/main/resources/db/migration/V1__baseline.sql",
    ]
    excluded = [
        ".codex/code-complexity-baseline.json",
        "docs/design.md",
        "frontend/package-lock.json",
        "testdata/fixture.json",
    ]

    assert all(gate.is_handwritten_code_path(PurePosixPath(path)) for path in included)
    assert not any(gate.is_handwritten_code_path(PurePosixPath(path)) for path in excluded)


def test_file_length_gate_counts_physical_lines_and_sorts_violations(
    tmp_path: Path,
) -> None:
    gate = load_file_length_gate()
    short = PurePosixPath("short.py")
    medium = PurePosixPath("frontend/medium.ts")
    longest = PurePosixPath("backend/longest.py")

    for relative, line_count in ((short, 2), (medium, 4), (longest, 6)):
        target = tmp_path.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line\n" * line_count, encoding="utf-8")

    assert gate.physical_line_count(tmp_path / "short.py") == 2
    assert gate.file_length_violations(
        tmp_path,
        [short, medium, longest],
        max_lines=3,
    ) == (
        gate.FileLengthViolation(path=longest, lines=6),
        gate.FileLengthViolation(path=medium, lines=4),
    )


def test_file_length_gate_includes_extensionless_shebang_scripts(tmp_path: Path) -> None:
    gate = load_file_length_gate()
    script = PurePosixPath("tools/release")
    target = tmp_path.joinpath(*script.parts)
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\nset -eu\necho release\n", encoding="utf-8")

    assert gate.has_shebang(target) is True
    assert gate.file_length_violations(tmp_path, [script], max_lines=2) == (
        gate.FileLengthViolation(path=script, lines=3),
    )


def test_file_length_gate_uses_the_repository_nul_safe_git_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gate = load_file_length_gate()
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=b"backend/app.py\0frontend/path with spaces.ts\0",
            stderr=b"",
        )

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    assert gate.repository_paths(tmp_path) == (
        PurePosixPath("backend/app.py"),
        PurePosixPath("frontend/path with spaces.ts"),
    )
    assert captured["command"] == [
        "git",
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["check"] is False


def test_file_length_gate_has_no_legacy_baseline_or_inline_escape_hatch() -> None:
    gate = load_file_length_gate()

    assert gate.MAX_PHYSICAL_LINES == 700
    assert not hasattr(gate, "BASELINE_PATH")
    assert not hasattr(gate, "EXCLUDED_PATHS")
