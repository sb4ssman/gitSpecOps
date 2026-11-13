"""Optional guided setup for gitSpecOps's command-line tools.

Run from this repository:

    python _build/setup_gitspecops.py     (or: run_setup.bat / run_setup.ps1 / run_setup.sh)

With no arguments, choose the command-line bootstrap or an individual setup item.
Non-interactive callers must name an action; --help never performs setup.
Use settings for guided updater preferences, settings-preview/settings-save for reviewed
noninteractive changes, and settings-migration-preview for read-only legacy mapping/readiness.
settings-existing-plan/save/status/resume implement the reviewed archive/policy-only switch.
The `bootstrap` action does two things:

  1. Creates a local virtual environment (.venv) with a predictable interpreter
     (and the desktop app's Qt). It prefers `uv sync` and falls back to the
     stdlib `venv` module. The project is NOT installed into .venv -- the tools
     run as scripts and there are no dependencies; an editable install would only
     add a startup-time `.pth` hook (see the note in pyproject.toml).

  2. Reports whether the runtime prerequisites (git, gh, uv) are available.

No shortcuts or launchers are written. Every command runs through `gitso.py`, e.g.
`python gitso.py commands`, or directly by its path, e.g. `python Special/update_archive.py --help`.
Auth is never touched here: users authenticate their own host CLI (`gh auth login`, ...).
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

from Basic._station import banner, choose, line, option, say  # noqa: E402

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
    banner("Building the gitSpecOps environment (.venv)")
    if create_venv_with_uv():
        return True
    print("\nFalling back to the stdlib environment builder...")
    return create_venv_with_stdlib()


def report_prerequisites() -> None:
    """Print whether git, gh, and uv are available (informational, non-fatal)."""
    banner("Prerequisite check")
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


def bootstrap() -> int:
    """Run the environment bootstrap after an explicit selection."""
    ok = build_environment()
    print()
    if ok and VENV_PYTHON.exists():
        print(f"[ok] Environment ready: {VENV_PYTHON}")
    else:
        print("[warn] Could not build .venv. The tools still run with any Python 3.11+.")

    report_prerequisites()
    print()
    print("Setup complete. Every command runs through gitso, e.g.:")
    print("  python gitso.py commands")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    from Special._settings.setup_cli import ACTIONS, add_arguments

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?",
                        choices=("walkthrough", "run", "bootstrap", "environment", "check", *ACTIONS),
                        help="walkthrough (a person at a console), run one command from the menu "
                             "without setting anything up, bootstrap the environment, check "
                             "prerequisites, or select a settings action")
    add_arguments(parser)
    return parser


def choose_action() -> str | None:
    """The setup menu: the walkthrough first, then single items."""
    banner("Setup", tagline=True)
    say()
    line("Individual tools work without fleet enrollment or the desktop app. Source use needs "
         "Python 3.11+ and Git; GitHub operations also need the GitHub CLI, signed in.")
    say()
    option("1", "Walk me through everything", "Recommended. Finds what this computer already has and "
           "asks about each part. Nothing changes until you review it.")
    option("2", "Run one command, without setting anything up", "Any Basic, Special or Elaborate "
           "command, straight from this folder: for example, register archive folders to keep updated "
           "(archive-manager). Installs nothing.")
    option("3", "Set up the Python environment", "This folder's .venv, then a prerequisite check.")
    option("4", "Check prerequisites", "Changes nothing.")
    option("5", "Configure standalone updater preferences", "Guided.")
    option("6", "Preview legacy settings migration", "Read-only.")
    option("7", "Use existing archive/security settings", "Guided review.")
    option("0", "Exit")
    try:
        answer = choose("12345670", "1")
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled; nothing has been changed.")
        return None
    return {"1": "walkthrough", "2": "run", "3": "bootstrap", "4": "check", "5": "settings",
            "6": "settings-migration-preview", "7": "settings-existing"}.get(answer)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    action = args.action
    if action is None:
        if args.json or args.approve is not None:
            parser.error("name an explicit settings action for JSON output or approval")
        if not sys.stdin.isatty():
            parser.print_help(file=sys.stderr)
            print("Name a setup action when there is no interactive terminal.", file=sys.stderr)
            return 2
        action = choose_action()
        if action is None:
            return 0
    from Special._settings.setup_cli import ACTIONS, EXISTING_ACTIONS, dispatch

    preference_fields = ("root", "exclude_path", "output_mode", "saved_format", "output_dir",
                         "log", "log_dir", "log_level", "log_max_bytes", "log_backups")
    has_preferences = any(getattr(args, name) is not None for name in preference_fields) or args.clear_roots or args.clear_exclusions
    has_settings_options = (has_preferences or args.settings_home is not None or args.legacy_sync_dir is not None
                            or args.approve is not None or args.json or args.show_paths or args.switch_id is not None
                            or args.legacy_writers_stopped or args.launcher_plan_reviewed)
    if action not in ACTIONS and has_settings_options:
        parser.error("settings options require a settings action")
    if action in ACTIONS:
        if args.approve is not None and action not in ("settings-save", "settings-existing-save"):
            parser.error("--approve is only valid with an explicit settings save")
        if action in EXISTING_ACTIONS:
            if has_preferences or args.legacy_sync_dir is not None:
                parser.error("existing-settings actions preserve archive/policy inputs; do not combine preference edits or fleet-directory options")
            if action == "settings-existing-plan" and (args.switch_id or args.legacy_writers_stopped or args.launcher_plan_reviewed):
                parser.error("the read-only plan does not accept switch execution options")
            if action == "settings-existing-save" and args.switch_id:
                parser.error("saving uses --approve; status/resume use --switch-id")
            if action == "settings-existing-status" and (args.legacy_writers_stopped or args.launcher_plan_reviewed):
                parser.error("read-only status does not accept execution acknowledgements")
            if action in ("settings-existing-status", "settings-existing-resume") and args.show_paths:
                parser.error("use the plan's --show-paths review before saving")
            if action == "settings-existing" and (args.json or args.switch_id or args.legacy_writers_stopped or args.launcher_plan_reviewed):
                parser.error("guided existing-settings setup obtains its approvals interactively; use plan/save for assisted use")
        elif args.switch_id or args.legacy_writers_stopped or args.launcher_plan_reviewed:
            parser.error("switch options require an existing-settings action")
        if action == "settings" and args.json:
            parser.error("use settings-preview/settings-save for noninteractive JSON")
        if action == "settings-migration-preview" and has_preferences:
            parser.error("migration preview does not change updater preferences")
        args.action = action
        return dispatch(args)
    if action == "walkthrough":
        if not sys.stdin.isatty():
            print("The walkthrough needs a person at a console; name another action.", file=sys.stderr)
            return 2
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from setup_walkthrough import Stop, walkthrough
        try:
            return walkthrough()
        except (EOFError, KeyboardInterrupt, Stop):
            print("\nSetup cancelled; nothing has been changed.")
            return 0
    if action == "run":
        if not sys.stdin.isatty():
            print("Choosing a command needs a person at a console; run gitso.py with the command "
                  "instead.", file=sys.stderr)
            return 2
        import gitso
        try:
            return gitso.menu()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled; nothing was run.")
            return 0
    if action == "bootstrap":
        return bootstrap()
    if action == "environment":
        return 0 if build_environment() else 1
    report_prerequisites()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
