"""Set up gitSpecOps on this computer: the standard installer flow, in the terminal.

Run from this repository:

    python setup_gitspecops.py     (or: run_setup.bat / run_setup.ps1 / run_setup.sh)

With no arguments (a person at a console) it is a setup wizard, the shelf's station script
standard (Sb4ssport-Authority knowledge/launchers.md): a start screen that leads with the
answer; Customize, where each choice (library folders, web view, start at sign-in, desktop Git
app, protected values, fleet) is separate and held until accepted; one Review of exactly what
will change and what will not; one key to apply it all on a run screen; then Done. Run again it
is the same front door: review and apply changes, repair, remove from this computer. The plan is
Elaborate/_fleet/setup_plan.py, shared with the web view's Setup page and with agents.
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
import copy
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


#: The shelf's publisher line, as on every other Sb4ssport station script (DCG-Taskforce,
#: PowerCycler): the same look across the shelf's tools.
PUBLISHER = "Sb4ssport-Alpha | https://sb4ssport-alpha.github.io"
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


def clear_screen() -> None:
    """Every screen starts on a clean window, as in the reference scripts; only for a person at
    a real console, never when output is captured or piped."""
    if COLOUR and sys.stdin.isatty():
        print("\x1b[2J\x1b[3J\x1b[H", end="", flush=True)


def menu_header(page: str) -> None:
    clear_screen()
    say()
    say(f"  {PRODUCT}  /  {page}", "accent")
    say(f"  {TAGLINE}")
    say(f"  {PUBLISHER}", "muted")
    say("-" * _width(), "muted")


def run_header(page: str, what: str) -> None:
    bar = "=" * _width()
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clear_screen()
    say()
    say(bar, "muted")
    say(f"  {PRODUCT}  /  {page}", "accent")
    say(f"  {PUBLISHER}", "muted")
    say(f"  {when} on {socket.gethostname()}  |  user {getpass.getuser()}  |  Python {platform.python_version()}", "detail")
    say(f"  {what}", "detail")
    say(bar, "muted")
    say()


def row(label: str, value: str, tone: str = "text") -> None:
    """A label padded to 20 columns, then the value; continuation lines align under the value."""
    room, rest, first = max(20, _width() - 22), _clean(value), True
    while True:
        if len(rest) > room:
            cut = rest.rfind(" ", 0, room + 1)
            cut = cut if cut > 0 else room
            piece, rest = rest[:cut].rstrip(), rest[cut:].lstrip()
        else:
            piece, rest = rest, ""
        say(f"  {label if first else '':<20}", "text", end="")
        say(piece, tone)
        first = False
        if not rest:
            return


def bullet(text: str, tone: str = "text") -> None:
    """`   . text`, wrapped so continuation lines start under the text."""
    room, rest, prefix = max(20, _width() - 5), _clean(text), "   . "
    while rest:
        if len(rest) > room:
            cut = rest.rfind(" ", 0, room + 1)
            cut = cut if cut > 0 else room
            piece, rest = rest[:cut].rstrip(), rest[cut:].lstrip()
        else:
            piece, rest = rest, ""
        say(prefix + piece, tone)
        prefix = "     "


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
    signed = "gh signed in" if gh_signed_in() else "gh not signed in (`gh auth login` for GitHub work)"
    return "ok", ", ".join(found) + (f" (optional {', '.join(optional)} absent)" if optional else "") + "; " + signed, ""


def gh_signed_in() -> bool:
    """Read-only: whether the GitHub CLI has a signed-in account."""
    if shutil.which("gh") is None:
        return False
    code, _output = _capture(["gh", "auth", "status"])
    return code == 0


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
        bullet(fact)
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


# --------------------------------------------------------------------------------------
# The setup wizard: the standard installer flow. A start screen that leads with the answer;
# Customize, where every choice is separate and held until accepted; one Review of exactly
# what will change; one key to apply it all on a run screen; then Done. Run again, it is the
# same front door: review and apply changes, repair, remove from this computer.
# The plan itself is Elaborate/_fleet/setup_plan.py, shared with the web view and agents.
# --------------------------------------------------------------------------------------
def ask(prompt: str, default: str = "") -> str:
    """One question; Enter takes the default."""
    return input(f"  {prompt} ").strip() or default


def choose(keys: str, default: str) -> str:
    """A choice from the listed keys; anything else is asked again."""
    while True:
        answer = ask(f"Choose [{default.upper()}]:", default).lower()
        if len(answer) == 1 and (answer in keys.lower() or (answer == "q" and "0" in keys)):
            return "0" if answer == "q" else answer
        line("Choose one of the keys shown; nothing has been changed.", "warning")


def app_python() -> str:
    """The Python that has the desktop app: the project's environment once it exists."""
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def detect_current():
    from Elaborate._fleet.setup_plan import detect
    return detect(python=app_python())


def plan_for(current, choices):
    from Elaborate._fleet.setup_plan import plan
    return plan(current, choices, python=app_python())


def _tray_running() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8760/v1/mark.svg", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def _short(path: str) -> str:
    appdata, home = os.environ.get("APPDATA"), str(Path.home())
    if WINDOWS and appdata and path.lower().startswith(appdata.lower()):
        return "%APPDATA%" + path[len(appdata):]
    return "~" + path[len(home):] if path.startswith(home) else path


def _web_words(web: str) -> str:
    from Elaborate._fleet.setup_plan import WEB_CHOICES
    return WEB_CHOICES.get(web, web)


def _client_words(current, client: str) -> str:
    from Special._sync.git_client import LABELS
    return LABELS.get(client, client) if client else ("none chosen" if current.clients else "none found")


def _fleet_words(current, choices) -> str:
    mode = choices.fleet_mode
    if mode == "keep":
        return "in a fleet: " + ", ".join(current.fleet_transports) if current.fleet_transports else "this computer only"
    if mode == "none":
        return "this computer only"
    ways = [name for name, on in (("Tailscale", choices.fleet_tailnet), ("synced folder", bool(choices.fleet_folder))) if on]
    return ("join a fleet" if mode == "join" else "start a fleet") + (f" ({', '.join(ways)})" if ways else "")


def settings_rows(current, choices) -> None:
    """The six choices with their values; a changed value is marked."""
    def mark(changed: bool) -> str:
        return "  (changed)" if changed else ""
    libraries = "; ".join(choices.libraries) or "none yet"
    row("Library folders", libraries + mark(choices.libraries != current.libraries),
        "text" if choices.libraries else "warning")
    row("Web view", _web_words(choices.web) + mark(choices.web != current.web))
    if choices.start_at_login is not None:
        row("Start at sign-in", ("yes" if choices.start_at_login else "no")
            + mark(choices.start_at_login != current.start_at_login))
    row("Desktop Git app", _client_words(current, choices.git_client) + mark(choices.git_client != current.git_client))
    words = len(current.protected.get("never_publish_words", []))
    count = len(current.protected.get("never_publish", [])) + words
    row("Protected values", f"{count}" + (f", {len(choices.protect)} to add" if choices.protect else ""))
    fleet_changed = choices.fleet_mode != "keep" and (choices.fleet_mode != "none" or bool(current.fleet_transports))
    row("Fleet", _fleet_words(current, choices) + mark(fleet_changed))


# --- the screens ---------------------------------------------------------------------
def start_screen(current, choices, pending: int) -> str:
    git_found = shutil.which("git") is not None
    menu_header("Setup")
    say()
    if not git_found:
        line("Needs attention", "error")
        line("Git is required. Install it from https://git-scm.com/downloads, then run setup again.")
    elif current.enrolled:
        line("gitSpecOps is set up on this computer", "success")
        line(f"As {current.machine}. Change anything below, repair it, or remove it.")
    else:
        line("Ready to set up", "success")
        line("This computer has what gitSpecOps needs. Nothing changes until you review and confirm.")
    say()
    row("Git", "found" if git_found else "missing", "success" if git_found else "error")
    row("GitHub", "signed in" if current.github else "not signed in (only needed for GitHub work)",
        "success" if current.github else "detail")
    row("Tailscale", "connected" if current.tailnet else "not connected (only needed for a fleet)",
        "success" if current.tailnet else "detail")
    if current.enrolled:
        say()
        settings_rows(current, choices)
    if pending:
        say()
        line(f"{pending} change{'s' if pending != 1 else ''} waiting for review.", "warning")
    say()
    keys = "0dm"
    if git_found:
        if current.enrolled:
            option("1", "Review and apply" if pending else "Repair", "Re-check the launchers and environment."
                   if not pending else "")
        else:
            option("1", "Review setup")
        option("2", "Customize")
        keys += "12"
        if current.enrolled:
            option("U", "Remove from this computer", "Your repositories and settings are kept.")
            keys += "u"
    option("D", "Details")
    option("M", "More tools", "Updater preferences and older settings.")
    option("0", "Exit without changes" if current.enrolled else "Exit without setting up")
    return choose(keys, "1" if git_found else "0")


def customize(current, choices):
    """Every choice separate; edits are kept only with [A]."""
    working = copy.deepcopy(choices)
    while True:
        menu_header("Customize")
        say()
        settings_rows(current, working)
        say()
        option("1", "Library folders")
        option("2", "Web view")
        if working.start_at_login is not None:
            option("3", "Start at sign-in")
        option("4", "Desktop Git app")
        option("5", "Protected values")
        option("6", "Fleet")
        option("A", "Use these settings")
        option("0", "Back without changes")
        key = choose("123456a0", "a")
        if key == "0":
            return choices
        if key == "a":
            return working
        {"1": edit_libraries, "2": edit_web, "3": edit_login, "4": edit_client,
         "5": edit_protected, "6": edit_fleet}[key](current, working)


def edit_libraries(current, working) -> None:
    from Special._sync.enrollment import find_libraries, whole_machine_starts
    found = []
    while True:
        menu_header("Library folders")
        say()
        line("The folders that hold your Git repositories. gitSpecOps watches the repositories in them.")
        say()
        for number, path in enumerate(working.libraries, 1):
            row(f"[{number}]", path)
        if not working.libraries:
            line("None yet.", "warning")
        if found:
            say()
            line("Found:", "accent")
            for letter, item in zip("abcdefghijklmnopqrstuvwxyz", found):
                row(f"[{letter.upper()}]", f"{item['path']}  ({item['repositories']} repositories)")
        say()
        option("L", "Look for folders", "Reads folder names only (no file contents, no Git) where you say.")
        option("P", "Add a folder by its path")
        if working.libraries:
            option("R", "Remove one from the list")
        option("0", "Done")
        answer = ask("Choose [0]:", "0")
        key = answer.lower()
        if key in ("0", "q"):
            return
        if key == "l":
            where = ask("Where to look: a folder, Enter for your home folder, or * for every drive:")
            starts = whole_machine_starts() if where == "*" else [Path(where or Path.home()).expanduser()]
            found = find_libraries(starts)[:26]
            if not found:
                line("No folders with repositories there.", "warning")
        elif key == "p":
            path = ask("Folder path:")
            if path and Path(path).expanduser().is_dir():
                working.libraries.append(str(Path(path).expanduser().resolve()))
            elif path:
                line("That folder does not exist.", "warning")
        elif key == "r" and working.libraries:
            pick = ask("Number to remove:")
            if pick.isdigit() and 1 <= int(pick) <= len(working.libraries):
                working.libraries.pop(int(pick) - 1)
        elif len(key) == 1 and key.isalpha() and found and ord(key) - ord("a") < len(found):
            path = found[ord(key) - ord("a")]["path"]
            if path not in working.libraries:
                working.libraries.append(path)


def edit_web(current, working) -> None:
    menu_header("Web view")
    say()
    line("The web view is the app's map of your repositories. Who may open it:")
    say()
    option("1", "This computer only", "Recommended.")
    option("2", "This computer and your own Tailscale devices", "A phone or another computer of yours.")
    option("3", "Not served", "The tray still works.")
    option("0", "Back")
    key = choose("1230", "0")
    if key != "0":
        working.web = {"1": "loopback", "2": "tailnet", "3": "off"}[key]


def edit_login(current, working) -> None:
    menu_header("Start at sign-in")
    say()
    line("Start gitSpecOps in the tray when you sign in, so it is always watching.")
    say()
    option("1", "Yes", "Adds one entry for your account; remove it any time here.")
    option("2", "No")
    option("0", "Back")
    key = choose("120", "0")
    if key != "0":
        working.start_at_login = key == "1"


def edit_client(current, working) -> None:
    from Special._sync.git_client import LABELS
    menu_header("Desktop Git app")
    say()
    if not current.clients:
        line("No supported desktop Git app was found (Sourcetree, GitHub Desktop). The web view still "
             "shows everything; it just cannot open a repository in one.")
        ask("Press Enter to go back:")
        return
    line("The app the web view opens a repository in.")
    say()
    keys = list(current.clients)
    for number, client in enumerate(keys, 1):
        option(str(number), LABELS.get(client, client))
    option("N", "None")
    option("0", "Back")
    key = choose("".join(str(n) for n in range(1, len(keys) + 1)) + "n0", "0")
    if key == "n":
        working.git_client = ""
    elif key != "0":
        working.git_client = keys[int(key) - 1]


def edit_protected(current, working) -> None:
    menu_header("Protected values")
    say()
    line("Values that must never be published: your name, email addresses, usernames. A security "
         "scan treats any of them as a high finding. Adding one scans nothing now.")
    say()
    row("Saved", f"{len(current.protected.get('never_publish', []))} anywhere in text, "
                 f"{len(current.protected.get('never_publish_words', []))} whole word only")
    for value, whole in working.protect:
        row("To add", f"{value[:2]}{'•' * max(1, len(value) - 3)}{value[-1:]}  ({'whole word' if whole else 'anywhere'})")
    say()
    option("A", "Add a value")
    option("0", "Done")
    while choose("a0", "0") == "a":
        value = ask("Value:")
        if value:
            whole = ask("Only as a whole word, for a short value that also occurs inside other words? [y/n] [n]:",
                        "n").lower() == "y"
            working.protect.append((value, whole))
            line("Will be added when you apply.", "success")
        option("A", "Add another")
        option("0", "Done")


def edit_fleet(current, working) -> None:
    menu_header("Fleet")
    say()
    line("A fleet is your machines watching each other: the map then shows every copy of every "
         "repository on all of them. Each machine needs gitSpecOps set up first.")
    say()
    row("Now", _fleet_words(current, working))
    row("Tailscale", "connected" if current.tailnet else "not connected", "success" if current.tailnet else "detail")
    row("Synced folders", ", ".join(_short(f) for f in current.synced_folders) or "none found")
    say()
    option("1", "This computer only")
    option("2", "Start a fleet with this computer", "Then add your other machines with this computer's key.")
    option("3", "Join a fleet", "Needs the key shown on a machine already in the fleet.")
    if current.enrolled:
        option("K", "Show this computer's fleet key", "To add another machine to its fleet.")
    option("0", "Back")
    key = choose("123k0" if current.enrolled else "1230", "0")
    if key == "0":
        return
    if key == "k":
        line("The key appears in this window only. Anyone, or any program reading this window, who has "
             "it can join your fleet.", "warning")
        if ask("Type SHOW to print it:") == "SHOW":
            subprocess.call([sys.executable, "Elaborate/setup_fleet.py", "fleet-key", "--show"], cwd=ROOT)
            ask("Press Enter when you have copied it:")
        return
    if key == "1":
        working.fleet_mode = "none"
        return
    working.fleet_mode = "new" if key == "2" else "join"
    if key == "3":
        working.fleet_key = ask("Paste the fleet key:")
    working.fleet_tailnet = current.tailnet and ask(
        "Share over Tailscale (recommended: your machines talk directly)? [y/n] [y]:", "y").lower() == "y"
    working.fleet_folder = ask("Also a folder your sync client copies (Enter to skip):")
    working.share_names = ask("Share repository names, branches and commit counts with your machines? [y/n] [y]:",
                              "y").lower() == "y"


def review(current, choices, changes) -> str:
    """One page: what will be done, what will not; then [I], [B] or [0]."""
    from Elaborate._fleet.setup_plan import problems
    menu_header("Review setup" if not current.enrolled else "Review changes")
    say()
    blockers = problems(current, choices)
    install = [] if (current.enrolled and VENV_PYTHON.exists()) else [
        "Launchers in this folder and its Python environment (.venv); nothing installed elsewhere."]
    if not choices.libraries:
        blockers = blockers + ["Add a library folder (Customize, 1): without one gitSpecOps has nothing to watch."]
    if not (install or changes):
        line("Nothing to change: everything is as you chose.", "success")
    else:
        line("These changes will be made:", "accent")
        for text in install:
            bullet(text)
        for change in changes:
            bullet(f"{change.title}: " + " ".join(change.review))
        if choices.libraries or current.enrolled:
            bullet("Then the app fetches your repositories' remotes, read-only, every 15 minutes "
                   "(it updates only Git's record of the remote).", "detail")
    say()
    line("Not changed: your repositories, your files, and anything else on this computer.", "muted")
    if blockers:
        say()
        for text in blockers:
            line(text, "warning")
    say()
    keys = "b0"
    if not blockers and (install or changes):
        option("I", "Set up" if not current.enrolled else "Apply")
        keys += "i"
    option("B", "Back")
    option("0", "Cancel")
    return choose(keys, "i" if "i" in keys else "b")


def apply_plan(current, choices, changes) -> bool:
    """The run screen: install steps, then every planned change, numbered and timed."""
    run_header("Setting up" if not current.enrolled else "Applying",
               "everything on the review; nothing else on this computer")
    install = not (current.enrolled and VENV_PYTHON.exists())
    steps = Steps((3 if install else 0) + len(changes))
    if install:
        steps.run("Launchers", launchers_step)
        steps.run("Python environment", build_environment_step)
        steps.run("Environment starts", check_environment_step)
    for change in changes:
        steps.run(change.title, lambda change=change: ("changed", change.apply(), ""))
    return finish(steps, "gitSpecOps is set up.", "Run setup again to finish; what completed is kept.")


def done_screen() -> None:
    if _tray_running():
        line("gitSpecOps is running: double-click its tray icon to see your map.", "success")
        ask("Press Enter to close:")
        return
    say()
    option("1", "Start gitSpecOps now", "Its tray icon appears; double-click it to see your map.")
    option("0", "Close")
    if choose("10", "1") == "1":
        start_tray()
        line("Started. The icon animates while it reads your libraries.", "success")
        ask("Press Enter to close:")


def start_tray() -> None:
    pythonw = VENV_PYTHON.with_name("pythonw.exe")
    command = [str(pythonw if WINDOWS and pythonw.exists() else VENV_PYTHON), str(ROOT / "App" / "tray.py")]
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if WINDOWS else 0
    subprocess.Popen(command, cwd=ROOT, creationflags=flags, start_new_session=not WINDOWS,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def remove_screen(current) -> None:
    """Remove from this computer: the sign-in entry, the launchers and the environment."""
    menu_header("Remove from this computer")
    say()
    inside = VENV_DIR.resolve() in Path(sys.executable).resolve().parents
    running = _tray_running()
    line("This will be removed:", "accent")
    if current.start_at_login:
        bullet("The start-at-sign-in entry")
    bullet("The launchers in this folder")
    bullet("The Python environment (.venv) in this folder")
    say()
    line(f"Kept: your repositories, and your settings ({_short(current.settings_file)}): libraries, "
         "protected values and fleet key, so setting up again is quick.", "muted")
    if running or inside:
        say()
        line("Quit gitSpecOps from its tray menu first." if running else
             "Setup is running from that environment; run it with another Python to remove it.", "warning")
        ask("Press Enter to go back:")
        return
    say()
    option("R", "Remove")
    option("0", "Cancel")
    if choose("r0", "0") != "r":
        return
    run_header("Removing", "the sign-in entry, the launchers and .venv in this folder")
    steps = Steps(3)
    if current.start_at_login:
        from Elaborate._fleet.setup_plan import _start_at_login
        steps.run("Start at sign-in", lambda: ("changed", _start_at_login(False, sys.executable), ""))
    else:
        steps.run("Start at sign-in", lambda: ("skipped", "was not on", ""))
    steps.run("Launchers", remove_launchers_step)
    steps.run("Python environment", remove_environment_step)
    finish(steps, "Removed. Your repositories and settings are kept.", "Some steps may have completed.")
    ask("Press Enter to close:")


def remove_launchers_step() -> tuple[str, str, str]:
    removed = 0
    for _tool_dir, _entry, base, _help in LAUNCHER_SPECS:
        for suffix in (".sh", ".ps1", ".bat"):
            path = ROOT / f"{base}{suffix}"
            if path.exists():
                path.unlink()
                removed += 1
    return ("changed" if removed else "skipped"), f"{removed} removed", ""


def remove_environment_step() -> tuple[str, str, str]:
    if not VENV_DIR.exists():
        return "skipped", "there was none", ""
    shutil.rmtree(VENV_DIR)
    return "changed", ".venv removed", ""


def details_screen(current) -> None:
    menu_header("Details")
    say()
    row("Python", f"{platform.python_version()}  {sys.executable}")
    row("Environment", str(VENV_DIR) if VENV_PYTHON.exists() else "not built")
    for name in ("git", "gh", "uv", "tailscale"):
        found = shutil.which(name)
        row(name, found or "not found", "text" if found else "detail")
    row("GitHub sign-in", "signed in" if current.github else "not signed in")
    row("Settings", current.settings_file)
    row("Start at sign-in", current.login_target or ("off" if current.start_at_login is False else "not available"))
    row("Synced folders", ", ".join(current.synced_folders) or "none found")
    row("Web view port", "8760 on this computer")
    say()
    ask("Press Enter to go back:")


def more_tools() -> str | None:
    menu_header("More tools")
    say()
    option("1", "Updater preferences (guided)")
    option("2", "Preview older settings migration", "Read-only.")
    option("3", "Use existing archive/security settings (guided review)")
    option("0", "Back")
    return {"1": "settings", "2": "settings-migration-preview", "3": "settings-existing"}.get(choose("1230", "0"))


def wizard(parser, args) -> int:
    """The front door for a person at a console."""
    from Elaborate._fleet.setup_plan import choices_from
    current = detect_current()
    choices = choices_from(current)
    while True:
        changes = plan_for(current, choices)
        key = start_screen(current, choices, len(changes) if current.enrolled else 0)
        if key == "0":
            return 0
        if key == "2":
            choices = customize(current, choices)
            continue
        if key == "1" and current.enrolled and not changes:
            bootstrap()
            ask("Press Enter to return to setup:")
            continue
        if key == "1":
            if not current.enrolled and not choices.libraries:
                edit_libraries(current, choices)
            while True:
                changes = plan_for(current, choices)
                answer = review(current, choices, changes)
                if answer == "i":
                    ok = apply_plan(current, choices, changes)
                    if ok:
                        done_screen()
                        return 0
                    ask("Press Enter to return to setup:")
                    break
                if answer == "b":
                    choices = customize(current, choices)
                    continue
                break
            current = detect_current()
            choices = choices_from(current)
            continue
        if key == "u":
            remove_screen(current)
            current = detect_current()
            choices = choices_from(current)
        elif key == "d":
            details_screen(current)
        elif key == "m":
            action = more_tools()
            if action:
                perform(parser, args, action)
                ask("Press Enter to return to setup:")


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
        try:
            return wizard(parser, args)
        except (EOFError, KeyboardInterrupt):
            notice("Setup cancelled", "Nothing more was changed; anything already applied is kept.", "warning")
            return 0
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
