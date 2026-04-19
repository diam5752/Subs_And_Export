#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_contract() -> dict[str, object]:
    contract_path = repo_root() / ".codex" / "quality-gates.json"
    return json.loads(contract_path.read_text(encoding="utf-8"))


def builtin_contract_check(root: Path) -> int:
    required = [
        root / "AGENT.md",
        root / ".codex" / "quality-gates.json",
        root / ".codex" / "acceptance-flows.md",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        print("BLOCKED: missing required enforcement files:")
        for item in missing:
            print(f"- {item}")
        return 2
    print("PASS: repository enforcement contract files are present.")
    return 0


def run_shell(root: Path, shell_command: str) -> int:
    completed = subprocess.run(
        shell_command,
        cwd=root,
        shell=True,
        executable="/bin/bash",
    )
    return completed.returncode


def run_command(name: str, commands: dict[str, object], root: Path, stack: list[str] | None = None) -> int:
    stack = stack or []
    if name in stack:
        print(f"ERROR: recursive quality command detected: {' -> '.join(stack + [name])}", file=sys.stderr)
        return 1

    command = commands.get(name)
    if not isinstance(command, dict):
        print(f"ERROR: unknown quality command `{name}`.", file=sys.stderr)
        return 1

    kind = str(command.get("kind", ""))
    if kind == "builtin":
        builtin = str(command.get("builtin", ""))
        if builtin == "contract":
            return builtin_contract_check(root)
        print(f"ERROR: unknown builtin `{builtin}` for `{name}`.", file=sys.stderr)
        return 1

    if kind == "shell":
        shell_command = str(command.get("shell", "")).strip()
        if not shell_command:
            print(f"ERROR: empty shell command for `{name}`.", file=sys.stderr)
            return 1
        print(f"RUN {name}: {shell_command}")
        return run_shell(root, shell_command)

    if kind == "composite":
        steps = command.get("steps", [])
        if not isinstance(steps, list) or not steps:
            print(f"ERROR: composite `{name}` has no steps.", file=sys.stderr)
            return 1
        for step in steps:
            if not isinstance(step, str):
                print(f"ERROR: invalid step in `{name}`.", file=sys.stderr)
                return 1
            code = run_command(step, commands, root, stack + [name])
            if code != 0:
                return code
        return 0

    if kind == "blocked":
        reason = str(command.get("message", "Quality gate is not implemented for this repository yet."))
        print(f"BLOCKED {name}: {reason}")
        return int(command.get("exit_code", 2))

    if kind == "noop":
        message = str(command.get("message", "No-op."))
        print(message)
        return 0

    print(f"ERROR: unsupported command kind `{kind}` for `{name}`.", file=sys.stderr)
    return 1


def list_commands(commands: dict[str, object]) -> int:
    for name in sorted(commands):
        command = commands[name]
        kind = command.get("kind", "unknown") if isinstance(command, dict) else "invalid"
        print(f"{name}\t{kind}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repository quality-gate commands.")
    parser.add_argument("command", nargs="?", default="check:fast", help="Command id such as `check:fast`.")
    parser.add_argument("--list", action="store_true", help="List available quality commands.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_contract()
    commands = contract.get("commands", {})
    if not isinstance(commands, dict):
        print("ERROR: `commands` section missing from .codex/quality-gates.json.", file=sys.stderr)
        return 1

    if args.list:
        return list_commands(commands)

    return run_command(args.command, commands, repo_root())


if __name__ == "__main__":
    raise SystemExit(main())
