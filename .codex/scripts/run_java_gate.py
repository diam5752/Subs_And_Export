#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REQUIRED_MAJOR = 25


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def java_major(java_home: Path) -> int | None:
    java_bin = java_home / "bin" / "java"
    if not java_bin.exists():
        return None

    completed = subprocess.run(
        [str(java_bin), "-version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
    if '"' not in first_line:
        return None
    version = first_line.split('"', maxsplit=2)[1]
    if version.startswith("1."):
        version = version.split(".", maxsplit=2)[1]
    else:
        version = version.split(".", maxsplit=1)[0]

    try:
        return int(version)
    except ValueError:
        return None


def candidate_homes() -> list[Path]:
    candidates: list[Path] = []

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home))

    java_home_tool = Path("/usr/libexec/java_home")
    if java_home_tool.exists():
        completed = subprocess.run(
            [str(java_home_tool), "-v", str(REQUIRED_MAJOR)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            candidates.append(Path(completed.stdout.strip()))

    for root in (
        Path.home() / "Library" / "Java" / "JavaVirtualMachines",
        Path("/Library/Java/JavaVirtualMachines"),
    ):
        if not root.exists():
            continue
        candidates.extend(path / "Contents" / "Home" for path in root.iterdir() if path.is_dir())

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def resolve_jdk25() -> Path | None:
    for candidate in candidate_homes():
        if java_major(candidate) == REQUIRED_MAJOR:
            return candidate
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR: pass the Java command to run, for example `./mvnw -B test`.", file=sys.stderr)
        return 1

    java_home = resolve_jdk25()
    if java_home is None:
        print(
            "BLOCKED check:java: JDK 25 is required but was not found. "
            "Install JDK 25 or set JAVA_HOME to a JDK 25 home.",
            file=sys.stderr,
        )
        return 2

    env = os.environ.copy()
    env["JAVA_HOME"] = str(java_home)
    env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env.get('PATH', '')}"

    print(f"RUN check:java with JAVA_HOME={java_home}")
    completed = subprocess.run(sys.argv[1:], cwd=repo_root(), env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
