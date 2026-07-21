"""Optional one-time bootstrap for gitSpecOps.

Run from this repository:

    uv run python setup_gitspecops.py     (or: run_setup.bat / run_setup.ps1 / run_setup.sh)

This does two things:

  1. Creates a local virtual environment (.venv) so the launchers can call its
     Python directly -- no per-launch `uv run` sync, and no hard dependency on
     `uv` being on PATH afterward. It prefers `uv sync` (honoring uv.lock) and
     falls back to the stdlib `venv` + `pip install -e .` when `uv` is absent.

  2. Reports whether the runtime prerequisites (git, gh, uv) are available.

Running this is OPTIONAL. The committed launchers already work without it by
falling back to `uv run`; setup just makes them faster and uv-independent.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WINDOWS = platform.system().lower() == "windows"
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if WINDOWS else "bin/python")


def _run(cmd: list[str]) -> int:
    """Run a command from the repo root, streaming its output. Returns the exit code."""
    print(f"  $ {' '.join(cmd)}")
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except OSError as exc:
        print(f"  (could not run {cmd[0]}: {exc})")
        return 1


def create_venv_with_uv() -> bool:
    """Create/refresh .venv via `uv sync`. Returns True on success."""
    if shutil.which("uv") is None:
        print("uv not found on PATH -- skipping the uv path.")
        return False
    print("Creating .venv with `uv sync`...")
    return _run(["uv", "sync"]) == 0


def _base_python() -> str:
    """A Python interpreter to build the venv with, avoiding .venv's own interpreter
    (it can't rebuild the venv it is currently running from). Falls back to sys.executable."""
    running = Path(sys.executable).resolve()
    try:
        inside_venv = VENV_DIR.resolve() in running.parents
    except OSError:
        inside_venv = False
    if not inside_venv:
        return sys.executable
    for name in ("py", "python3", "python"):
        found = shutil.which(name)
        if found and Path(found).resolve() != running:
            return found
    return sys.executable  # nothing better available; let venv report the real error


def create_venv_with_stdlib() -> bool:
    """Create .venv with the stdlib venv module and install the project. Returns True on success."""
    print("Creating .venv with the stdlib `venv` module...")
    if _run([_base_python(), "-m", "venv", str(VENV_DIR)]) != 0:
        return False
    if not VENV_PYTHON.exists():
        print(f"ERROR: expected interpreter not found at {VENV_PYTHON}")
        return False
    print("Installing the project into .venv (`pip install -e .`)...")
    # Upgrade pip quietly first; ignore its result, then do the editable install.
    _run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    return _run([str(VENV_PYTHON), "-m", "pip", "install", "-e", ".", "--quiet"]) == 0


def build_environment() -> bool:
    """Build .venv, preferring uv and falling back to the stdlib. Returns True on success."""
    print("=" * 60)
    print("Building the gitSpecOps environment (.venv)")
    print("=" * 60)
    if create_venv_with_uv():
        return True
    print("\nFalling back to the stdlib environment builder...")
    return create_venv_with_stdlib()


def report_prerequisites() -> None:
    """Print whether git, gh, and uv are available (informational, non-fatal)."""
    print()
    print("=" * 60)
    print("Prerequisite check")
    print("=" * 60)
    checks = [
        ("git", True, "Required. Install from https://git-scm.com/downloads"),
        ("gh", True, "Required by the org duplicator. Install from https://cli.github.com"),
        ("uv", False, "Optional (speeds up setup). Install from https://docs.astral.sh/uv/"),
    ]
    for name, required, hint in checks:
        found = shutil.which(name)
        if found:
            print(f"  [ok]   {name:<4} -> {found}")
        else:
            tag = "MISSING" if required else "absent "
            print(f"  [{tag}] {name:<4} -> {hint}")
    print()
    print("Note: `gh` must also be authenticated (`gh auth login`) before the")
    print("org duplicator can talk to GitHub.")


def main(argv: list[str] | None = None) -> int:
    _ = argv
    ok = build_environment()
    print()
    if ok and VENV_PYTHON.exists():
        print(f"[ok] Environment ready: {VENV_PYTHON}")
        print("     Launchers will now use this interpreter directly.")
    else:
        print("[warn] Could not build .venv. The launchers will still work by")
        print("       falling back to `uv run` (which needs uv on PATH).")

    report_prerequisites()
    print()
    print("Setup complete. Run a tool via its launcher, e.g.:")
    print("  github-org-duplicator\\duplicate-github-org.bat" if WINDOWS
          else "  github-org-duplicator/duplicate-github-org.sh")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
