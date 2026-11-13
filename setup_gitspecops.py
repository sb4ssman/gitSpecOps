"""Optional guided setup for gitSpecOps's command-line tools.

Run from this repository:

    python setup_gitspecops.py     (or: run_setup.bat / run_setup.ps1 / run_setup.sh)

With no arguments, choose the command-line bootstrap or an individual setup item.
Non-interactive callers must name an action; --help never performs setup.
Use settings for guided updater preferences, settings-preview/settings-save for reviewed
noninteractive changes, and settings-migration-preview for read-only legacy mapping/readiness.
settings-existing-plan/save/status/resume implement the reviewed archive/policy-only switch.
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
`python3 Special/update_archive.py --help`, or via `uv run python ...`.
Auth is never touched here: users authenticate their own host CLI (`gh auth login`, ...).
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WINDOWS = platform.system().lower() == "windows"
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if WINDOWS else "bin/python")

# --------------------------------------------------------------------------------------
# The station script look (Sb4ssport's terminal standard: two screens, 72-wide rules, steps
# "[n/total] label  status  seconds  detail", status always in words). Each script carries
# its own small copy of these helpers; there is no shared runtime.
# --------------------------------------------------------------------------------------
PRODUCT = "gitSpecOps"
TAGLINE = "Every repository on every machine: seen, kept current, protected"


def _publisher() -> str:
    """The publisher line, from the project's own metadata (pyproject.toml's first author), so
    no account name is written into source files."""
    try:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        author = re.search(r'authors\s*=\s*\[\s*\{\s*name\s*=\s*"([^"]+)"', text).group(1)
    except (OSError, AttributeError):
        return PRODUCT
    return f"{author} | https://github.com/{author}/{PRODUCT}"


PUBLISHER = _publisher()
#: Console colour names, as ANSI codes (the terminal's theme decides the exact shade).
TONES = {"accent": "96", "muted": "36", "text": "37", "detail": "90", "strong": "97",
         "success": "92", "warning": "93", "error": "91"}
STATUS_TONES = {"ok": "success", "changed": "warning", "skipped": "detail", "FAILED": "error"}


def _colour_enabled() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if WINDOWS:
        try:  # turn on ANSI colours in a classic Windows console
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel.SetConsoleMode(handle, mode.value | 0x0004)
        except (AttributeError, OSError):
            return False
    return True


COLOUR = _colour_enabled()


def _width() -> int:
    columns = shutil.get_terminal_size((80, 24)).columns
    return min(72, columns - 1) if columns >= 42 else 72


def _clean(text) -> str:
    """Anything printed that came from outside the script: no control characters."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text)))


def say(text: str = "", tone: str = "text", end: str = "\n") -> None:
    print(f"\x1b[{TONES[tone]}m{text}\x1b[0m" if COLOUR and text else text, end=end, flush=True)


def line(text: str = "", tone: str = "text") -> None:
    """Indented text, wrapped at spaces (paths after a separator) to the console width."""
    if not text:
        say()
        return
    room, rest = _width() - 2, _clean(text)
    while len(rest) > room:
        cut = rest.rfind(" ", 0, room + 1)
        if cut <= 0:
            cut = max(rest.rfind("\\", 0, room), rest.rfind("/", 0, room)) + 1 or room
        say("  " + rest[:cut].rstrip(), tone)
        rest = rest[cut:].lstrip()
    say("  " + rest, tone)


def menu_header(page: str) -> None:
    say()
    say(f"  {PRODUCT}  /  {page}", "accent")
    say(f"  {TAGLINE}")
    say(f"  {PUBLISHER}", "muted")
    say("-" * _width(), "muted")


def run_header(page: str, what: str) -> None:
    bar = "=" * _width()
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    say()
    say(bar, "muted")
    say(f"  {PRODUCT}  /  {page}", "accent")
    say(f"  {PUBLISHER}", "muted")
    say(f"  {when} on {socket.gethostname()}  |  user {getpass.getuser()}  |  Python {platform.python_version()}", "detail")
    say(f"  {what}", "detail")
    say(bar, "muted")
    say()


def row(label: str, value: str, tone: str = "text") -> None:
    say(f"  {label:<20}", "text", end="")
    say(_clean(value), tone)


def option(key: str, label: str, explanation: str = "") -> None:
    say(f"  [{key}] ", "accent", end="")
    say(label)
    if explanation:
        say(f"      {explanation}", "muted")


def notice(title: str, message: str, tone: str) -> None:
    say()
    line(title, tone)
    line(message)


class Steps:
    """Numbered steps: `[n/total] label` padded to 30, then status, seconds and detail."""

    def __init__(self, total: int):
        self.total, self.index, self.results = total, 0, []

    def run(self, label: str, action) -> str:
        self.index += 1
        say(f"  [{self.index}/{self.total}] {label:<30}", "strong", end="")
        started = time.monotonic()
        try:
            status, detail, output = action()
        except Exception as exc:  # noqa: BLE001 - a step reports its failure; setup goes on honestly
            status, detail, output = "FAILED", type(exc).__name__, str(exc)
        say(f" {status:<8}", STATUS_TONES[status], end="")
        say(f"{time.monotonic() - started:5.1f}s  {_clean(detail)}", "detail")
        if status == "FAILED" and output:
            for text in [l for l in _clean_lines(output)][-8:]:  # the last words, not a stack trace
                say(f"        {text}", "detail")
        self.results.append((label, status, detail))
        return status


def _clean_lines(output: str) -> list[str]:
    return [_clean(l).rstrip() for l in str(output).splitlines() if l.strip()]


def _capture(cmd: list[str]) -> tuple[int, str]:
    """Run a command from the repo root and keep its output for when it fails."""
    try:
        done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="replace")
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except OSError as exc:
        return 1, f"could not run {cmd[0]}: {exc}"


def create_venv_with_uv() -> tuple[bool, str]:
    """Create/refresh .venv via `uv sync`. Returns (success, output)."""
    if shutil.which("uv") is None:
        return False, "uv not found on PATH"
    # --extra app keeps the tray's Qt (PySide6): a plain sync would remove it, since uv makes
    # .venv match exactly what is asked for.
    code, output = _capture(["uv", "sync", "--extra", "app"])
    return code == 0, output


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


def create_venv_with_stdlib() -> tuple[bool, str]:
    """Create a bare .venv with the stdlib venv module. Returns (success, output).

    Nothing is installed into it: the tools are stdlib-only scripts, so the venv just
    needs to be a clean interpreter the launchers can point at.
    """
    code, output = _capture([_base_python(), "-m", "venv", str(VENV_DIR)])
    if code != 0:
        return False, output
    if not VENV_PYTHON.exists():
        return False, "the environment was created without its Python interpreter"
    return True, output


def build_environment_step() -> tuple[str, str, str]:
    """The environment as one step: uv when present (keeps the app's Qt), else the stdlib."""
    existed = VENV_PYTHON.exists()
    ok, output = create_venv_with_uv()
    how = "uv sync, with the desktop app's Qt"
    if not ok:
        fallback, more = create_venv_with_stdlib()
        ok, output, how = fallback, output + "\n" + more, "Python's venv (no uv; the tray needs uv or PySide6)"
    if not ok:
        return "FAILED", "could not build .venv", output
    return ("ok" if existed else "changed"), f".venv ready via {how}", ""


def build_environment() -> bool:
    """Build .venv, preferring uv and falling back to the stdlib. Returns True on success."""
    run_header("Python environment", f"builds or refreshes .venv in {ROOT.name}")
    steps = Steps(2)
    built = steps.run("Python environment", build_environment_step)
    steps.run("Environment starts", check_environment_step)
    return finish(steps, "The environment is ready.", "The launchers still work through `uv run` when uv is on PATH.")


def check_environment_step() -> tuple[str, str, str]:
    """A step that starts something checks it actually runs."""
    if not VENV_PYTHON.exists():
        return "skipped", "no .venv; launchers fall back to `uv run`", ""
    code, output = _capture([str(VENV_PYTHON), "-c", "import sys; print(sys.version.split()[0])"])
    return ("ok", f"Python {output.strip()} runs", "") if code == 0 else ("FAILED", "the .venv Python does not start", output)


PREREQUISITES = (
    ("git", True, "required: https://git-scm.com/downloads"),
    ("gh", True, "required for GitHub work: https://cli.github.com (then `gh auth login`)"),
    ("uv", False, "optional, faster setup and the desktop app: https://docs.astral.sh/uv/"),
)


def prerequisites_step() -> tuple[str, str, str]:
    found = [name for name, _required, _hint in PREREQUISITES if shutil.which(name)]
    missing = [name for name, required, _hint in PREREQUISITES if required and not shutil.which(name)]
    if missing:
        return "FAILED", f"missing: {', '.join(missing)}", "\n".join(
            f"{name}: {hint}" for name, required, hint in PREREQUISITES if name in missing)
    optional = [name for name, required, _hint in PREREQUISITES if not required and name not in found]
    return "ok", ", ".join(found) + (f" (optional {', '.join(optional)} absent)" if optional else ""), ""


def report_prerequisites() -> None:
    """Show git, gh and uv, as rows (read-only, never fails setup)."""
    menu_header("Prerequisites")
    say()
    for name, required, hint in PREREQUISITES:
        found = shutil.which(name)
        row(name, "found" if found else ("missing: " + hint if required else "absent: " + hint),
            "success" if found else ("error" if required else "detail"))
    notice("Nothing was changed.", "gh must also be signed in (`gh auth login`) for GitHub work.", "success")


def summary_facts() -> list[str]:
    """What this folder now has, in a few facts (the steps above already said how it went)."""
    launcher = ROOT / ("suggest-sync.ps1" if WINDOWS else "suggest-sync.sh")
    qt = (VENV_DIR / "Lib/site-packages/PySide6").exists() or any(VENV_DIR.glob("lib/python*/site-packages/PySide6"))
    facts = [f"Launchers {'in ' + ROOT.name if launcher.exists() else 'not written'}",
             (".venv ready" + (", with the desktop app" if qt else ", tools only (the desktop app needs uv)"))
             if VENV_PYTHON.exists() else "no .venv: tools run through `uv run`"]
    missing = [name for name, required, _hint in PREREQUISITES if required and not shutil.which(name)]
    if missing:
        facts.append("Missing: " + ", ".join(missing))
    return facts


def finish(steps: "Steps", ready: str, otherwise: str) -> bool:
    failed = [label for label, status, _detail in steps.results if status == "FAILED"]
    say()
    line("Summary", "accent")
    for fact in summary_facts():
        line(f". {fact}")
    if failed:
        notice("Setup incomplete", f"{', '.join(failed)} did not finish; some steps may have completed. {otherwise}", "error")
        return False
    notice("Ready", ready, "success")
    return True


# --------------------------------------------------------------------------------------
# Generated convenience launchers
# --------------------------------------------------------------------------------------
# One launcher per tool, written into the repo root; only this OS's launcher type is
# generated. help_on_no_args makes a bare launch show --help instead of starting
# interactive work.

LAUNCHER_SPECS = [
    # (tool_dir, entry_script, launcher_base, help_on_no_args)
    ("Special", "update_archive.py", "update-archive", True),
    ("Special", "archive_manager.py", "manage-archives", False),
    ("Special", "duplicate_org.py", "duplicate-github-org", False),
    ("Special", "suggest_sync.py", "suggest-sync", True),
    ("App", "tray.py", "gitspecops-tray", False),
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


def write_launchers() -> list[tuple[str, bool]]:
    """Generate the launchers: one per tool, repo root, this OS only. Idempotent.
    Returns (name, written) for each launcher."""
    written = []
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
            written.append((name, _write_if_changed(target, content, exe)))
    return written


def launchers_step() -> tuple[str, str, str]:
    results = write_launchers()
    changed = sum(1 for _name, wrote in results if wrote)
    detail = f"{len(results)} launchers in the repository folder" + (f", {changed} written" if changed else ", all current")
    return ("changed" if changed else "ok"), detail, ""


def launchers() -> int:
    run_header("Launchers", f"writes the command launchers into {ROOT.name} (generated, not committed)")
    steps = Steps(1)
    steps.run("Launchers", launchers_step)
    return 0 if finish(steps, "Run a tool through its launcher, e.g. "
                       + ("suggest-sync.bat --help" if WINDOWS else "./suggest-sync.sh --help") + ".", "") else 1


def bootstrap() -> int:
    """Launchers, environment and prerequisites, as one run screen."""
    run_header("Setting up", f"launchers and .venv in {ROOT.name}; nothing outside this folder")
    steps = Steps(4)
    steps.run("Launchers", launchers_step)
    steps.run("Python environment", build_environment_step)
    steps.run("Environment starts", check_environment_step)
    steps.run("Prerequisites", prerequisites_step)
    ok = finish(steps, "Start the app with " + ("gitspecops-tray.bat" if WINDOWS else "./gitspecops-tray.sh")
                + ", or run a tool through its launcher, e.g. "
                + ("suggest-sync.bat --help" if WINDOWS else "./suggest-sync.sh --help") + ".",
                "Run setup again after fixing what is listed; the launchers fall back to `uv run`.")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    from Special._settings.setup_cli import ACTIONS, add_arguments

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?",
                        choices=("bootstrap", "launchers", "environment", "check", *ACTIONS),
                        help="bootstrap launchers/environment, check prerequisites, or select a settings action")
    add_arguments(parser)
    return parser


def readiness() -> tuple[bool, list[tuple[str, str, str]]]:
    """Lead with the answer: is this folder set up, and what does this machine have?"""
    venv = VENV_PYTHON.exists()
    launcher = ROOT / ("suggest-sync.ps1" if WINDOWS else "suggest-sync.sh")
    rows = [("Python environment", ".venv ready" if venv else "not built yet", "success" if venv else "warning"),
            ("Launchers", "present" if launcher.exists() else "not written yet", "success" if launcher.exists() else "warning")]
    for name, required, _hint in PREREQUISITES:
        found = shutil.which(name) is not None
        rows.append((name, "found" if found else ("missing" if required else "absent (optional)"),
                     "success" if found else ("error" if required else "detail")))
    return venv and launcher.exists(), rows


def choose_action() -> str | None:
    """The menu screen: readiness first, then the choices, with a recommended default."""
    while True:
        ready, rows = readiness()
        menu_header("Setup")
        say()
        line("Set up" if ready else "Not set up yet", "success" if ready else "warning")
        line("Each tool also runs on its own, without enrolling a machine or using the desktop app.")
        say()
        for label, value, tone in rows:
            row(label, value, tone)
        say()
        option("1", "Set up launchers and Python environment", "Writes launchers here and builds .venv; nothing outside this folder.")
        option("2", "Choose one setup item")
        option("3", "Check prerequisites", "Changes nothing.")
        option("4", "Updater preferences (guided)")
        option("5", "Preview legacy settings migration", "Read-only.")
        option("6", "Use existing archive/security settings (guided review)")
        option("0", "Exit")
        default = "0" if ready else "1"
        try:
            answer = input(f"  Choose [{default}]: ").strip().lower() or default
            if answer in ("0", "q"):
                return None
            if answer == "1":
                return "bootstrap"
            if answer == "3":
                return "check"
            if answer == "4":
                return "settings"
            if answer == "5":
                return "settings-migration-preview"
            if answer == "6":
                return "settings-existing"
            if answer == "2":
                menu_header("Setup items")
                say()
                option("1", "Write the launchers")
                option("2", "Build or refresh the Python environment")
                option("3", "Updater preferences")
                option("4", "Preview legacy settings migration")
                option("5", "Use existing archive/security settings")
                option("0", "Back")
                item = input("  Choose [0]: ").strip().lower() or "0"
                if item in ("0", "b", "q"):
                    continue
                if item in ("1", "2"):
                    return {"1": "launchers", "2": "environment"}[item]
                if item in ("3", "4", "5"):
                    return {"3": "settings", "4": "settings-migration-preview", "5": "settings-existing"}[item]
            line("Choose one of the listed keys; nothing has been changed.", "warning")
        except (EOFError, KeyboardInterrupt):
            notice("Setup cancelled", "Nothing has been changed.", "warning")
            return None


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
        # A person at the menu: run the chosen item, wait so its result can be read (a
        # double-clicked window closes the moment setup ends), then show the menu again.
        while True:
            action = choose_action()
            if action is None:
                return 0
            code = perform(parser, args, action)
            try:
                answer = input("\n  Press Enter to return to the menu, or Q to quit: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return code
            if answer == "q":
                return code
    return perform(parser, args, action)


def perform(parser, args, action: str) -> int:
    """Run one setup action, named on the command line or chosen from the menu."""
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
    if action == "bootstrap":
        return bootstrap()
    if action == "launchers":
        return launchers()
    if action == "environment":
        return 0 if build_environment() else 1
    report_prerequisites()
    return 0


def run() -> int:
    """main(), failing honestly: an unexpected error says what happened in one plain sentence,
    and the full details go to a file (never a stack trace on the screen)."""
    try:
        return main()
    except (KeyboardInterrupt, EOFError):
        notice("Setup cancelled", "Some steps may have completed; run setup again to finish.", "warning")
        return 130
    except Exception as exc:  # noqa: BLE001 - the last line of defence for a person at a console
        import tempfile
        import traceback
        report = Path(tempfile.gettempdir()) / "gitspecops-setup-error.txt"
        try:
            report.write_text(traceback.format_exc(), encoding="utf-8")
            where = f"Details: {report}"
        except OSError:
            where = "The details could not be saved."
        notice("Setup stopped unexpectedly", f"{type(exc).__name__}: {_clean(exc)}. Some steps may have "
               f"completed. {where}", "error")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
