"""Setup for gitSpecOps: the walkthrough, or one setup item at a time.

Run from this repository:

    run_setup.bat / run_setup.ps1 / run_setup.sh     (or: python _build/setup_gitspecops.py)

With no arguments, a person at a terminal gets the setup menu. Named actions:

    walkthrough   the guided setup (needs a person at a terminal)
    part          set up, change or repair one part of the walkthrough on its own
    run           choose one command from a list and run it, without setting anything up
    environment   build this folder's .venv (with uv when it is installed), then check
    check         show what this computer has: Git, the GitHub CLI, uv. Changes nothing.
    uninstall     stop the app and remove what setup added, after a review; settings on request

gitSpecOps needs no setup to run: every command works straight from this folder through
`gitso`, e.g. `python gitso.py commands`. Sign-ins are never touched here: you sign in to your
own tools (`gh auth login`).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# This script lives in _build/; the repository root is its parent, and the layers import from there.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Basic._station import banner, choose, line, notice, option, row, say  # noqa: E402

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
    # --extra app keeps the tray's Qt (PySide6): a plain sync would remove it, since uv makes
    # .venv match exactly what is asked for.
    print("Creating .venv with `uv sync --extra app`...")
    return _run(["uv", "sync", "--extra", "app"]) == 0


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
    needs to be a clean interpreter.
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
    banner("Setup  /  Python environment", f"folder: {VENV_DIR}")
    if create_venv_with_uv():
        return True
    print("\nFalling back to the stdlib environment builder...")
    return create_venv_with_stdlib()


def _gh_signed_in() -> bool:
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def report_prerequisites() -> None:
    """Show what this computer has for gitSpecOps; changes nothing."""
    banner("Setup  /  This computer")
    say()
    git, gh, uv = shutil.which("git"), shutil.which("gh"), shutil.which("uv")
    row("Git", "found" if git else "missing: required", "success" if git else "error")
    if gh:
        signed_in = _gh_signed_in()
        row("GitHub CLI", "found, signed in" if signed_in else "found, not signed in",
            "success" if signed_in else "warning")
    else:
        row("GitHub CLI", "not installed (optional)", "text")
    row("uv", "found" if uv else "not installed (optional)", "success" if uv else "text")
    say()
    line("Git is required: every operation runs your own git.", "muted")
    line("The GitHub CLI is how gitSpecOps talks to GitHub with your own sign-in: anything that "
         "lists, copies or creates repositories there. Everything else works without it."
         + ("" if not gh or signed_in else " To sign in, run: gh auth login"), "muted")
    line("uv installs the desktop app's one dependency (Qt) into this folder's .venv. The "
         "command-line tools need only Python.", "muted")
    if not git:
        line("Install Git: https://git-scm.com/downloads", "warning")
    if not gh:
        line("GitHub CLI, if you want it: https://cli.github.com", "muted")
    if not uv:
        line("uv, if you want the desktop app: https://docs.astral.sh/uv/", "muted")


def bootstrap() -> int:
    """Build the environment, then show what this computer has."""
    ok = build_environment()
    if ok and VENV_PYTHON.exists():
        notice("Environment ready", str(VENV_PYTHON), "success")
    else:
        notice("No .venv built", "The commands still run with any Python 3.11 or later.", "warning")
    report_prerequisites()
    say()
    line("Every command runs through gitso, for example: python gitso.py commands", "muted")
    return 0 if ok else 1


ACTIONS = ("walkthrough", "part", "run", "environment", "check", "uninstall")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitso setup", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", choices=ACTIONS,
                        help="what to do; with none, a person at a terminal gets the menu")
    return parser


def choose_action() -> str | None:
    """The setup menu: the walkthrough first, then single items."""
    banner("Setup", tagline=True)
    say()
    line("gitSpecOps needs no setup to run: every command works straight from this folder. Setup "
         "adds the parts you want, such as the gitso command, this machine's map and a fleet.")
    say()
    option("1", "Walk me through everything", "Recommended. Finds what this computer already has and "
           "asks about each part. Nothing changes until you review it.")
    option("2", "Set up one part", "Pick one part to set up, change or repair on its own: the gitso "
           "command, library folders, protection, the fleet, and the rest.")
    option("3", "Use the commands without installing anything", "Choose any command from a list and run "
           "it from this folder. Any time: python gitso.py <command>.")
    option("4", "Check this computer", "Git, the GitHub CLI and uv: what is there and what each is "
           "for. Changes nothing.")
    option("5", "Uninstall", "Stop the app and remove what setup added: start at sign-in, the gitso "
           "command, the fleet. Asks before deleting your settings; shows everything before it acts.")
    option("0", "Exit")
    try:
        answer = choose("123450", "1")
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled; nothing has been changed.")
        return None
    return {"1": "walkthrough", "2": "part", "3": "run", "4": "check", "5": "uninstall"}.get(answer)


def run_one_command(back: bool) -> int:
    """The command menu. From setup's own menu (`back`), a blank answer goes back to it."""
    import gitso
    try:
        code = gitso.menu(cancel="go back to setup" if back else "cancel")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; nothing was run.")
        return 0
    if back and code is not None:
        say()
        line("Back to setup.", "detail")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action is not None:
        return perform(parser, args, args.action)
    if not sys.stdin.isatty():
        parser.print_help(file=sys.stderr)
        print("Name a setup action when there is no interactive terminal.", file=sys.stderr)
        return 2
    return menu_loop(parser, args)


def menu_loop(parser, args) -> int:
    """Every item is a visit: when it finishes, is stopped or fails, the menu comes back. Only
    [0] Exit (or the end of input) leaves setup."""
    while True:
        action = choose_action()
        if action is None:
            return 0
        if action == "run":
            run_one_command(back=True)
            continue
        code = 0
        try:
            code = perform(parser, args, action)
        except (KeyboardInterrupt, EOFError):
            say()
            line("Stopped.", "warning")
        except SystemExit as stop:  # an item that ends with exit still comes back here
            code = stop.code if isinstance(stop.code, int) else (1 if stop.code else 0)
        if code:
            say()
            line("That item did not finish; what it said is above.", "warning")
        say()
        try:
            input("  Press Enter to go back to the setup menu: ")
        except (EOFError, KeyboardInterrupt):
            print("\nSetup closed.")
            return 0


def perform(parser, args, action) -> int:
    """One setup action, from the menu or named on the command line."""
    if action in ("walkthrough", "part", "uninstall"):
        if not sys.stdin.isatty():
            print(f"The {action} item needs a person at a terminal; name another action.", file=sys.stderr)
            return 2
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from setup_walkthrough import Stop, choose_part, uninstall, walkthrough
        try:
            if action == "walkthrough":
                return walkthrough()
            if action == "uninstall":
                return uninstall()
            part = choose_part()
            return 0 if part is None else walkthrough(only=part)
        except (EOFError, KeyboardInterrupt, Stop):
            print("\nSetup cancelled; nothing has been changed.")
            return 0
    if action == "run":
        if not sys.stdin.isatty():
            print("Choosing a command needs a person at a terminal; run gitso with the command "
                  "instead.", file=sys.stderr)
            return 2
        return run_one_command(back=False)
    if action == "environment":
        return bootstrap()
    report_prerequisites()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
