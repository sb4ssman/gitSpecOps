"""Every OS folder under `_os/` implements the same components with the same functions.

The point of `_os/` is that Windows, Linux and macOS are peers out of the box: a component
added for one OS without the others is a port waiting to be forgotten. This test loads every
OS's files on whatever machine runs it, which also enforces the rule that nothing under `_os/`
does OS-only work at import time.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

OS_NAMES = ("windows", "linux", "macos")
OS_DIR = ROOT / "_os"
failures: list[str] = []


def public_functions(module) -> set[str]:
    return {name for name, value in vars(module).items()
            if callable(value) and not name.startswith("_")
            and str(getattr(value, "__module__", "")).startswith("_os.")}


components = {name: sorted(p.stem for p in (OS_DIR / name).glob("*.py") if p.stem != "__init__")
              for name in OS_NAMES}
reference = components["windows"]
if not reference:
    failures.append("_os/windows/ has no components")
for name in OS_NAMES:
    if components[name] != reference:
        failures.append(f"_os/{name}/ has {components[name]}, expected {reference}")

for component in reference:
    surfaces = {}
    for name in OS_NAMES:
        try:
            module = importlib.import_module(f"_os.{name}.{component}")
        except Exception as exc:  # noqa: BLE001 - any import failure is the finding
            failures.append(f"_os/{name}/{component}.py does not import here: {exc!r}")
            continue
        surfaces[name] = public_functions(module)
    if len(set(map(frozenset, surfaces.values()))) > 1:
        failures.append(f"{component}: functions differ across OSes: {surfaces}")

# current.py must offer every component, so a caller never has to reach into an OS folder.
tree = ast.parse((OS_DIR / "current.py").read_text(encoding="utf-8"))
offered = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
           and (node.module or "").startswith("_os.") for alias in node.names}
missing = set(reference) - offered
if missing:
    failures.append(f"_os/current.py does not offer: {sorted(missing)}")

# Nothing under _os/ may import the layers above it.
for path in OS_DIR.rglob("*.py"):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        for imported in names:
            if imported.split(".")[0] in ("Basic", "Special", "Elaborate", "App"):
                failures.append(f"{path.relative_to(ROOT)} imports {imported}")

if failures:
    print("FAIL:")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)
print(f"ALL-OS-PARITY-TESTS-PASS ({len(reference)} component(s) x {len(OS_NAMES)} OSes)")
