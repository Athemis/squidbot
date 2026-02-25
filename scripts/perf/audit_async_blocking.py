"""Audit async hot paths for blocking filesystem and subprocess calls.

This script scans selected production modules and fails if it finds blocking calls
that should be offloaded from the event loop. It also writes the full audit output
to ``.sisyphus/evidence/task-9-audit.txt``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

EVIDENCE_PATH = Path(".sisyphus/evidence/task-9-audit.txt")
REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPE_ROOTS = (
    REPO_ROOT / "squidbot" / "adapters" / "tools",
    REPO_ROOT / "squidbot" / "adapters" / "channels",
    REPO_ROOT / "squidbot" / "adapters" / "persistence",
)
SUBPROCESS_ROOT = REPO_ROOT / "squidbot"
FS_METHODS = {"read_text", "write_text", "read_bytes", "write_bytes", "iterdir"}


@dataclass(frozen=True)
class Violation:
    """Represents a single blocking-call audit failure."""

    path: Path
    line: int
    message: str


def _is_python_file(path: Path) -> bool:
    return path.is_file() and path.suffix == ".py" and "tests" not in path.parts


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if _is_python_file(path))


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _is_in_async_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.AsyncFunctionDef):
            return True
        current = parents.get(current)
    return False


def _enclosing_async_function(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> ast.AsyncFunctionDef | None:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.AsyncFunctionDef):
            return current
        current = parents.get(current)
    return None


def _enclosing_sync_function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.FunctionDef):
            return current.name
        if isinstance(current, ast.AsyncFunctionDef):
            return None
        current = parents.get(current)
    return None


def _is_asyncio_to_thread(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "asyncio"
        and func.attr == "to_thread"
    )


def _is_subprocess_run(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr == "run"
    )


def _filesystem_method_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in FS_METHODS:
        return func.attr
    return None


def _parse_file(path: Path, violations: list[Violation]) -> tuple[ast.Module | None, list[str]]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    try:
        return ast.parse(source), lines
    except SyntaxError as exc:
        line = exc.lineno or 1
        violations.append(
            Violation(path=path, line=line, message=f"Could not parse file: {exc.msg}")
        )
        return None, lines


def _scan_subprocess_calls(path: Path, violations: list[Violation]) -> None:
    tree, _ = _parse_file(path, violations)
    if tree is None:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_subprocess_run(node):
            violations.append(
                Violation(
                    path=path,
                    line=node.lineno,
                    message="Use async subprocess APIs instead of subprocess.run().",
                )
            )


def _scan_filesystem_calls(path: Path, violations: list[Violation]) -> None:
    tree, lines = _parse_file(path, violations)
    if tree is None:
        return
    parents = _build_parent_map(tree)
    offloaded_helpers_by_async_fn: dict[ast.AsyncFunctionDef, set[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        helper_names: set[str] = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call) or not _is_asyncio_to_thread(inner):
                continue
            if not inner.args:
                continue
            first_arg = inner.args[0]
            if isinstance(first_arg, ast.Name):
                helper_names.add(first_arg.id)
        offloaded_helpers_by_async_fn[node] = helper_names

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_in_async_function(node, parents):
            continue

        method_name = _filesystem_method_name(node)
        if method_name is None:
            continue

        line = node.lineno
        line_text = lines[line - 1] if 0 < line <= len(lines) else ""
        if "asyncio.to_thread" in line_text:
            continue

        enclosing_async = _enclosing_async_function(node, parents)
        if enclosing_async is None:
            continue
        offloaded_helpers = offloaded_helpers_by_async_fn.get(enclosing_async, set())
        enclosing_sync_function_name = _enclosing_sync_function_name(node, parents)
        if (
            enclosing_sync_function_name is not None
            and enclosing_sync_function_name in offloaded_helpers
        ):
            continue

        violations.append(
            Violation(
                path=path,
                line=line,
                message=(
                    f"Blocking Path.{method_name}() in async function without asyncio.to_thread."
                ),
            )
        )


def _format_output(violations: list[Violation]) -> list[str]:
    lines: list[str] = []
    if violations:
        lines.append(f"FAILED: found {len(violations)} blocking-call violation(s)")
        for violation in sorted(
            violations, key=lambda item: (str(item.path), item.line, item.message)
        ):
            rel_path = violation.path.relative_to(REPO_ROOT)
            lines.append(f"{rel_path}:{violation.line}: {violation.message}")
        return lines

    lines.append("OK")
    return lines


def main() -> int:
    violations: list[Violation] = []

    for path in _iter_python_files(SUBPROCESS_ROOT):
        _scan_subprocess_calls(path, violations)

    for root in SCOPE_ROOTS:
        for path in _iter_python_files(root):
            _scan_filesystem_calls(path, violations)

    output_lines = _format_output(violations)
    output_text = "\n".join(output_lines) + "\n"
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(output_text, encoding="utf-8")
    print(output_text, end="")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
