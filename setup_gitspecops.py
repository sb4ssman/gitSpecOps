"""Optional guided setup for gitSpecOps's command-line tools.

Run from this repository:

    python setup_gitspecops.py     (or: run_setup.bat / run_setup.ps1 / run_setup.sh)

With no arguments, choose the command-line bootstrap or an individual setup item.
Non-interactive callers must name an action; --help never performs setup.
The `bootstrap` action does three things:

  1. Writes the per-tool convenience launchers (.sh / .ps1 / .bat in the repository
     root). Launchers are GENERATED, not committed -- edit LAUNCHER_SPECS here, not
     the launchers. The .py tools can always be run directly without any launcher.

  2. Creates a local virtual environment (.venv) so the launchers can call its
     Python directly -- no per-launch `uv run` sync, and no hard dependency on
     `uv` being on PATH afterward. It prefers `uv sync` and falls back to the
     stdlib `venv` module. The project is NOT installed into .venv -- the tools
     run as scripts and there are no dependencies; an editable install would only
     add a startup-time `.pth` hook (see the note in pyproject.toml).

  3. Reports whether the runtime prerequisites (git, gh, uv) are available.

Running this is OPTIONAL. Without it, run the tools directly, e.g.
`python3 Special/archive_update.py --help`, or via `uv run python ...`.
Auth is never touched here: users authenticate their own host CLI (`gh auth login`, ...).
"""

from __future__ import annotations

import argparse
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
    """Create a bare .venv with the stdlib venv module. Returns True on success.

    Nothing is installed into it: the tools are stdlib-only scripts, so the venv just
    needs to be a clean interpreter the launchers can point at.
    """
    print("Creating .venv with the stdlib `venv` module...")
    if _run([_base_python(), "-m", "venv", str(VENV_DIR)]) != 0:
        return False
    if not VENV_PYTHON.exists():
        print(f"ERROR: expected interpreter not found at {VENV_PYTHON}")
        return False
    return True


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


# --------------------------------------------------------------------------------------
# Generated convenience launchers
# --------------------------------------------------------------------------------------
# One launcher per tool, written into the repo root; only this OS's launcher type is
# generated. help_on_no_args makes a bare launch show --help instead of starting
# interactive work.

LAUNCHER_SPECS = [
    # (tool_dir, entry_script, launcher_base, help_on_no_args)
    ("Special", "archive_update.py", "update-archive", True),
    ("Elaborate", "archive_manage.py", "manage-archives", False),
    ("Special/duplicate_org", "duplicate_org.py", "duplicate-github-org", False),
    ("git-sync-suggester", "sync_suggester.py", "suggest-sync", True),
]

SH_TEMPLATE = """#!/usr/bin/env sh
# Generated by setup_gitspecops.py -- edit setup_gitspecops.py, not this file.
# Prefers the repo's .venv; falls back to `uv run`. Lives in the repo root.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ "$#" -eq 0 ] && __HELP_SH__; then
    set -- --help
fi
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python "__TOOL_DIR__/__ENTRY__" "$@"
else
    exec uv run python "__TOOL_DIR__/__ENTRY__" "$@"
fi
"""

PS1_TEMPLATE = """# Generated by setup_gitspecops.py -- edit setup_gitspecops.py, not this file.
# Prefers the repo's .venv; falls back to `uv run`. Lives in the repo root.
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$venvPy = Join-Path $repo ".venv\\Scripts\\python.exe"
$forward = @args
__HELP_PS__Push-Location $repo
try {
    if (Test-Path $venvPy) {
        & $venvPy "__TOOL_DIR__/__ENTRY__" @forward
    } else {
        uv run python "__TOOL_DIR__/__ENTRY__" @forward
    }
} finally {
    Pop-Location
}
exit $LASTEXITCODE
"""

BAT_TEMPLATE = """@echo off
rem Generated shim: hands off to the .ps1. Edit setup_gitspecops.py, not this file.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0__BASE__.ps1" %*
"""


def _write_if_changed(path: Path, content: str, executable: bool = False) -> bool:
    """Write content unless the file already matches. Returns True when written."""
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
    except OSError:
        pass
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)
    return True


def write_launchers() -> None:
    """Generate the launchers: one per tool, repo root, this OS only. Idempotent."""
    print("Writing convenience launchers (generated, not committed)...")
    for tool_dir, entry, base, help_on_no_args in LAUNCHER_SPECS:
        sh = (SH_TEMPLATE
              .replace("__HELP_SH__", "true" if help_on_no_args else "false")
              .replace("__TOOL_DIR__", tool_dir)
              .replace("__ENTRY__", entry))
        ps1 = (PS1_TEMPLATE
               .replace("__HELP_PS__", "if ($forward.Count -eq 0) { $forward = @('--help') }\n"
                        if help_on_no_args else "")
               .replace("__TOOL_DIR__", tool_dir)
               .replace("__ENTRY__", entry))
        bat = BAT_TEMPLATE.replace("__BASE__", base)
        for name, content, exe in ((f"{base}.sh", sh, True),
                                   (f"{base}.ps1", ps1, False),
                                   (f"{base}.bat", bat, False)):
            is_windows_launcher = name.endswith((".ps1", ".bat"))
            if is_windows_launcher != WINDOWS:
                continue  # generate only what this OS can use
            target = ROOT / name
            changed = _write_if_changed(target, content, exe)
            print(f"  {'wrote' if changed else 'ok  '} {name}")


def bootstrap() -> int:
    """Run the existing launcher/environment bootstrap after an explicit selection."""
    write_launchers()
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
    print("  suggest-sync.bat --help" if WINDOWS else "  ./suggest-sync.sh --help")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?",
                        choices=("bootstrap", "launchers", "environment", "check"),
                        help="bootstrap everything below, or select launchers, environment or prerequisite check")
    return parser


def choose_action() -> str | None:
    """Explain optional participation and select an implemented setup action."""
    print("gitSpecOps setup\n"
          "Individual tools work without fleet enrollment or the desktop app.\n"
          "Source use needs Python 3.11+ and Git; GitHub operations also need authenticated gh.\n"
          "This command-line bootstrap can create convenience launchers and a Python environment.")
    while True:
        print("\n1. Set up command-line launchers and Python environment\n"
              "2. Choose a setup item\n"
              "3. Check prerequisites without changing anything\n"
              "0. Exit")
        try:
            answer = input("Choose [0]: ").strip() or "0"
            if answer == "0":
                return None
            if answer == "1":
                return "bootstrap"
            if answer == "3":
                return "check"
            if answer == "2":
                print("\n1. Generate convenience launchers\n"
                      "2. Create or refresh the Python environment\n"
                      "0. Back")
                item = input("Choose [0]: ").strip() or "0"
                if item == "0":
                    continue
                if item in ("1", "2"):
                    return {"1": "launchers", "2": "environment"}[item]
            print("Choose one of the listed items; nothing has been changed.")
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled; nothing has been changed.")
            return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    action = args.action
    if action is None:
        if not sys.stdin.isatty():
            parser.print_help(file=sys.stderr)
            print("Name a setup action when there is no interactive terminal.", file=sys.stderr)
            return 2
        action = choose_action()
        if action is None:
            return 0
    if action == "bootstrap":
        return bootstrap()
    if action == "launchers":
        write_launchers()
        return 0
    if action == "environment":
        return 0 if build_environment() else 1
    report_prerequisites()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
