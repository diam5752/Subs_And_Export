#!/usr/bin/env python3

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
PMD_SUPPRESSION = re.compile(
    r"@SuppressWarnings\s*\([^)]*PMD[^)]*\)",
    re.DOTALL,
)


@dataclass(frozen=True)
class SuppressionFinding:
    path: PurePosixPath
    line: int
    marker: str


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


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _marker_finding(
    text: str,
    path: PurePosixPath,
    marker: str,
) -> SuppressionFinding | None:
    offset = text.find(marker)
    if offset < 0:
        return None
    return SuppressionFinding(
        path=path,
        line=_line_number(text, offset),
        marker=marker,
    )


def _jscpd_findings(
    text: str,
    path: PurePosixPath,
) -> tuple[SuppressionFinding, ...]:
    markers = ("jscpd:" + "ignore-start", "jscpd:" + "ignore-end")
    return tuple(finding for marker in markers if (finding := _marker_finding(text, path, marker)) is not None)


def _formatter_findings(
    text: str,
    path: PurePosixPath,
) -> tuple[SuppressionFinding, ...]:
    markers = ("fmt:" + " off", "fmt:" + " skip", "prettier-" + "ignore")
    return tuple(finding for marker in markers if (finding := _marker_finding(text, path, marker)) is not None)


def _pmd_findings(
    text: str,
    path: PurePosixPath,
) -> tuple[SuppressionFinding, ...]:
    findings: list[SuppressionFinding] = []
    no_pmd = _marker_finding(text, path, "NO" + "PMD")
    if no_pmd is not None:
        findings.append(no_pmd)
    findings.extend(
        SuppressionFinding(
            path=path,
            line=_line_number(text, match.start()),
            marker='@SuppressWarnings("PMD...")',
        )
        for match in PMD_SUPPRESSION.finditer(text)
    )
    return tuple(findings)


def suppression_findings(
    root: Path,
    paths: tuple[PurePosixPath, ...],
) -> tuple[SuppressionFinding, ...]:
    findings: list[SuppressionFinding] = []
    for relative in paths:
        candidate = root.joinpath(*relative.parts)
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # Scan every tracked or new non-ignored UTF-8 text file. Formatter and
        # clone-tool coverage grows as new source/config formats are added, so
        # a suffix allow-list would silently create a new inline escape hatch.
        findings.extend(_jscpd_findings(text, relative))
        findings.extend(_formatter_findings(text, relative))
        if relative.suffix.lower() == ".java":
            findings.extend(_pmd_findings(text, relative))
    return tuple(sorted(findings, key=lambda item: (str(item.path), item.line, item.marker)))


def main() -> int:
    try:
        findings = suppression_findings(REPO_ROOT, repository_paths())
    except (OSError, RuntimeError) as error:
        print(f"ERROR: unable to evaluate quality suppressions: {error}", file=sys.stderr)
        return 2
    if findings:
        print(
            "FAIL: inline formatter, PMD, or duplicate-code suppressions are forbidden:",
            file=sys.stderr,
        )
        for finding in findings:
            print(
                f"- {finding.path}:{finding.line}: {finding.marker}",
                file=sys.stderr,
            )
        return 1
    print("PASS: no inline formatter, PMD, or duplicate-code suppression markers found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
