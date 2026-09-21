"""The layer stack's one-way import rule, read straight from the source.

    _os  ->  Basic  ->  Special  ->  Elaborate  ->  App

A file may import the stdlib, `_os`, its own layer's plumbing, and any layer before its own.
It may not import:

- a later layer (App is optional; nothing may come to depend on it, and so on down);
- a sibling *command* in its own layer (a file without an underscore) -- shared behavior
  belongs in that layer's plumbing, or the two commands are secretly one;
- anything outside the stack: the legacy tool folders, `shared/`, or third-party packages
  (the runtime is stdlib-only).

`_os/` may import only the stdlib and itself. Relative imports are not used anywhere.
Every import statement counts, including those inside functions: a lazy import is still a
dependency.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

ORDER = ["_os", "Basic", "Special", "Elaborate", "App"]
RANK = {name: rank for rank, name in enumerate(ORDER)}
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
failures: list[str] = []
checked = 0


def is_command(module_parts: list[str]) -> bool:
    """A module path names a command when none of its parts below the layer is underscored."""
    return bool(module_parts) and not any(part.startswith("_") for part in module_parts)


def imported_modules(node: ast.AST) -> list[str]:
    """Dotted module names an import statement loads. `from X import y` loads X.y when
    X/y.py exists (a module), else X (y is a name inside it)."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    parts = (node.module or "").split(".")
    return [".".join(parts + [alias.name]) if ROOT.joinpath(*parts, f"{alias.name}.py").exists()
            else node.module for alias in node.names]


for layer in ORDER:
    folder = ROOT / layer
    if not folder.is_dir():
        continue
    for path in sorted(folder.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        checked += 1
        rel = path.relative_to(ROOT).as_posix()
        own_parts = list(path.relative_to(folder).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.ImportFrom) and node.level:
                failures.append(f"{rel}:{node.lineno} relative import")
                continue
            for module in imported_modules(node):
                top, *rest = module.split(".")
                where = f"{rel}:{node.lineno} imports {module}"
                if top in STDLIB:
                    continue
                if top not in RANK:
                    failures.append(f"{where} — outside the stack (tool folder, shared/, or a "
                                    "third-party package)")
                    continue
                if layer == "_os" and top != "_os":
                    failures.append(f"{where} — _os/ imports only the stdlib and itself")
                elif RANK[top] > RANK[layer]:
                    failures.append(f"{where} — {layer} may not depend on the later {top}")
                elif top == layer and layer != "_os" and is_command(rest) and rest != own_parts:
                    failures.append(f"{where} — sideways: a command importing a sibling command")

if failures:
    print("FAIL:")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)
print(f"ALL-IMPORT-DIRECTION-TESTS-PASS ({checked} files in the stack)")
