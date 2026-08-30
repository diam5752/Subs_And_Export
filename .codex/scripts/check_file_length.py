#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_PHYSICAL_LINES = 700
CODE_SUFFIXES = frozenset(
    {
        ".bash",
        ".bat",
        ".cjs",
        ".c",
        ".cc",
        ".clj",
        ".cljs",
        ".cmd",
        ".cpp",
        ".css",
        ".cs",
        ".cxx",
        ".dart",
        ".ex",
        ".exs",
        ".erl",
        ".fs",
        ".fsx",
        ".go",
        ".gql",
        ".gradle",
        ".graphql",
        ".groovy",
        ".h",
        ".hcl",
        ".hh",
        ".htm",
        ".html",
        ".hpp",
        ".hrl",
        ".hxx",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".less",
        ".lua",
        ".mako",
        ".mjs",
        ".mk",
        ".m",
        ".mm",
        ".php",
        ".pl",
        ".proto",
        ".properties",
        ".ps1",
        ".py",
        ".pyi",
        ".r",
        ".rb",
        ".rs",
        ".sass",
        ".scala",
        ".scss",
        ".sh",
        ".sql",
        ".svelte",
        ".swift",
        ".tf",
        ".toml",
        ".ts",
        ".tsx",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)
CODE_FILENAMES = frozenset({"Caddyfile", "Dockerfile", "GNUmakefile", "Makefile"})


@dataclass(frozen=True)
class FileLengthViolation:
    path: PurePosixPath
    lines: int


def is_handwritten_code_path(path: PurePosixPath) -> bool:
    name = path.name
    return (
        path.suffix.lower() in CODE_SUFFIXES or name in CODE_FILENAMES or name.startswith(("Caddyfile.", "Dockerfile."))
    )


def repository_paths(root: Path = REPO_ROOT) -> tuple[PurePosixPath, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {detail or 'unknown error'}")
    return tuple(
        PurePosixPath(raw.decode("utf-8", errors="surrogateescape")) for raw in completed.stdout.split(b"\0") if raw
    )


def physical_line_count(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def has_shebang(path: Path) -> bool:
    with path.open("rb") as source:
        return source.read(2) == b"#!"


def file_length_violations(
    root: Path,
    paths: Sequence[PurePosixPath],
    max_lines: int = MAX_PHYSICAL_LINES,
) -> tuple[FileLengthViolation, ...]:
    violations = []
    for relative in paths:
        candidate = root.joinpath(*relative.parts)
        if not candidate.is_file():
            continue
        if not is_handwritten_code_path(relative) and not has_shebang(candidate):
            continue
        lines = physical_line_count(candidate)
        if lines > max_lines:
            violations.append(FileLengthViolation(path=relative, lines=lines))
    return tuple(sorted(violations, key=lambda item: (-item.lines, str(item.path))))


def main() -> int:
    try:
        violations = file_length_violations(REPO_ROOT, repository_paths())
    except (OSError, RuntimeError) as error:
        print(f"ERROR: unable to evaluate tracked code file lengths: {error}", file=sys.stderr)
        return 2

    if violations:
        print(
            f"FAIL: {len(violations)} repository hand-written code files exceed {MAX_PHYSICAL_LINES} physical lines:",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"- {violation.path}: {violation.lines}", file=sys.stderr)
        return 1

    print(f"PASS: every repository hand-written code file is at or below {MAX_PHYSICAL_LINES} physical lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
