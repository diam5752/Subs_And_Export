#!/usr/bin/env python3

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend" / "app"
FRONTEND_ROOT = REPO_ROOT / "frontend" / "src"

TS_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:type\s+)?(?:[^'"]+?\s+from\s+)?['"]([^'"]+)['"]""",
)


def build_python_modules(root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        module = ".".join(parts)
        if module:
            modules[module] = path
    return modules


def resolve_python_import(
    source_module: str,
    import_name: str,
    level: int,
    modules: dict[str, Path],
) -> str | None:
    if level:
        source_parts = source_module.split(".")
        base_parts = source_parts[:-level]
        target_parts = base_parts + ([part for part in import_name.split(".") if part] if import_name else [])
    else:
        if import_name.startswith("backend.app."):
            import_name = import_name.removeprefix("backend.app.")
        elif import_name.startswith("app."):
            import_name = import_name.removeprefix("app.")
        else:
            return None
        target_parts = [part for part in import_name.split(".") if part]

    if not target_parts:
        return None

    for length in range(len(target_parts), 0, -1):
        candidate = ".".join(target_parts[:length])
        if candidate in modules:
            return candidate
    return None


def build_python_graph(root: Path) -> tuple[dict[Path, set[Path]], list[str]]:
    modules = build_python_modules(root)
    graph = {path: set() for path in modules.values()}
    violations: list[str] = []

    for module_name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = resolve_python_import(module_name, alias.name, 0, modules)
                    if target:
                        graph[path].add(modules[target])
                    elif alias.name.startswith("frontend"):
                        violations.append(
                            f"Cross-stack import: {path.relative_to(REPO_ROOT)} imports {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                target = resolve_python_import(module_name, module, node.level, modules)
                if target:
                    graph[path].add(modules[target])
                elif module.startswith("frontend"):
                    violations.append(
                        f"Cross-stack import: {path.relative_to(REPO_ROOT)} imports {module}"
                    )

    return graph, violations


def resolve_ts_import(source_path: Path, spec: str) -> Path | None:
    if spec.startswith("@/"):
        candidate_base = FRONTEND_ROOT / spec.removeprefix("@/")
    elif spec.startswith("."):
        candidate_base = (source_path.parent / spec).resolve()
    else:
        return None

    candidates = [
        candidate_base,
        candidate_base.with_suffix(".ts"),
        candidate_base.with_suffix(".tsx"),
        candidate_base / "index.ts",
        candidate_base / "index.tsx",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def build_ts_graph(root: Path) -> tuple[dict[Path, set[Path]], list[str]]:
    files = {
        path: set()
        for path in root.rglob("*")
        if path.suffix in {".ts", ".tsx"} and "__tests__" not in path.parts and "__mocks__" not in path.parts
    }
    violations: list[str] = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in TS_IMPORT_RE.finditer(text):
            spec = match.group(1)
            if "backend" in spec:
                violations.append(
                    f"Cross-stack import: {path.relative_to(REPO_ROOT)} imports {spec}"
                )
                continue
            target = resolve_ts_import(path, spec)
            if target and target in files:
                files[path].add(target)

    return files, violations


def find_cycles(graph: dict[Path, set[Path]]) -> list[list[Path]]:
    visited: set[Path] = set()
    stack: list[Path] = []
    on_stack: set[Path] = set()
    cycles: list[list[Path]] = []
    seen_signatures: set[tuple[str, ...]] = set()

    def dfs(node: Path) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in on_stack:
                start = stack.index(neighbor)
                cycle = stack[start:] + [neighbor]
                signature = tuple(sorted(str(item.relative_to(REPO_ROOT)) for item in cycle[:-1]))
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    cycles.append(cycle)
        stack.pop()
        on_stack.remove(node)

    for node in graph:
        if node not in visited:
            dfs(node)
    return cycles


def format_cycle(cycle: list[Path]) -> str:
    parts = [str(path.relative_to(REPO_ROOT)) for path in cycle]
    return " -> ".join(parts)


def main() -> int:
    python_graph, python_violations = build_python_graph(BACKEND_ROOT)
    ts_graph, ts_violations = build_ts_graph(FRONTEND_ROOT)

    violations = python_violations + ts_violations
    python_cycles = find_cycles(python_graph)
    ts_cycles = find_cycles(ts_graph)

    if violations or python_cycles or ts_cycles:
        print("Architecture check failed.")
        for violation in violations:
            print(f"- {violation}")
        for cycle in python_cycles:
            print(f"- Backend cycle: {format_cycle(cycle)}")
        for cycle in ts_cycles:
            print(f"- Frontend cycle: {format_cycle(cycle)}")
        return 1

    print("PASS: no cross-stack imports or internal import cycles detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
