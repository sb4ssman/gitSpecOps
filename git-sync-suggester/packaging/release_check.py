"""Read-only desktop-release readiness check; it creates, uploads and tags nothing.

Run from a checkout before building a public desktop artifact:

    python git-sync-suggester/packaging/release_check.py

It makes missing prerequisites visible rather than turning a source checkout into a release by
accident.  A green result is a local gate, not evidence that a GitHub release was published.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ("fleet_dashboard.html", "fleet_standard.css", "fleet_client.js",
          "fleet_view.js", "fleet_standard.js")


def _git(root: Path, *args) -> tuple[bool, str]:
    try:
        result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True,
                                timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Git unavailable"
    return result.returncode == 0, (result.stdout or result.stderr).strip()


def _pyinstaller_available() -> bool:
    """The documented build runs ``python -m PyInstaller`` inside this interpreter's env."""
    return importlib.util.find_spec("PyInstaller") is not None


def release_checks(root: Path = ROOT) -> list[tuple[str, bool, str]]:
    """Return `(gate, pass, explanation)` rows without altering repository or release state."""
    root = Path(root).resolve()
    version_path = root / "shared" / "version.py"
    spec_path = root / "git-sync-suggester" / "packaging" / "GitSpecOpsSync.spec"
    ui = root / "git-sync-suggester" / "ui"
    rows = []
    version = ""
    try:
        source = version_path.read_text(encoding="utf-8")
        module = ast.parse(source)
        version = next((node.value.value for node in module.body if isinstance(node, ast.Assign)
                        for target in node.targets if isinstance(target, ast.Name)
                        and target.id == "VERSION" and isinstance(node.value, ast.Constant)), "")
        rows.append(("version", bool(version), f"version {version or 'not declared'}"))
    except (OSError, SyntaxError):
        rows.append(("version", False, "shared/version.py is unreadable"))
    try:
        spec = spec_path.read_text(encoding="utf-8")
        ast.parse(spec)
        missing = [name for name in ASSETS if not (ui / name).is_file()]
        rows.append(("desktop recipe", not missing,
                     "all dashboard assets found" if not missing else "missing: " + ", ".join(missing)))
    except (OSError, SyntaxError):
        rows.append(("desktop recipe", False, "PyInstaller recipe is unreadable"))
    clean, detail = _git(root, "diff", "--check")
    rows.append(("patch whitespace", clean, "clean" if clean else detail or "failed"))
    tracked, detail = _git(root, "status", "--porcelain")
    rows.append(("clean worktree", tracked and not detail, "clean" if tracked and not detail else
                 "commit or intentionally carry these changes before release"))
    tagged, tags = _git(root, "tag", "--points-at", "HEAD")
    want = f"v{version}" if version else ""
    rows.append(("version tag", tagged and want in tags.split(),
                 f"{want} points at HEAD" if tagged and want in tags.split() else
                 f"tag HEAD as {want or 'v<version>'} before publishing"))
    has_pyinstaller = _pyinstaller_available()
    rows.append(("PyInstaller", has_pyinstaller,
                 "available" if has_pyinstaller else
                 "install in a disposable build environment before building"))
    return rows


def main() -> int:
    rows = release_checks()
    for name, passed, detail in rows:
        print(f"{'ok' if passed else 'missing':<7} {name:<18} {detail}")
    return 0 if all(passed for _name, passed, _detail in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
