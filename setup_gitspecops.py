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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The station look (Sb4ssport-Authority knowledge/launchers.md) lives in Basic/_station.py, shared
# with every gitSpecOps tool, so setup draws exactly the screens the other tools draw.
from Basic._station import (  # noqa: E402
    COLOUR, PRODUCT, Steps, ask, bullet, choose, clear_screen, line, menu_header, notice, option, row,
    run_header, say, section, summary)
from Basic._station import clean as _clean, clean_lines as _clean_lines, width as _width, wrap as _wrap  # noqa: E402,F401


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
    if client:
        return LABELS.get(client, client)
    found = ", ".join(LABELS.get(name, name) for name in current.clients)
    return f"none chosen; {found} found" if found else "none found"


def _fleet_words(current, choices) -> str:
    mode = choices.fleet_mode
    if mode == "keep":
        return "in a fleet: " + ", ".join(current.fleet_transports) if current.fleet_transports else "this computer only"
    if mode == "none":
        return "this computer only"
    ways = [name for name, on in (("Tailscale", choices.fleet_tailnet), ("synced folder", bool(choices.fleet_folder))) if on]
    return ("join a fleet" if mode == "join" else "start a fleet") + (f" ({', '.join(ways)})" if ways else "")


def install_state() -> dict:
    """What this folder has: the environment, the desktop app, the launchers; and the tray."""
    desktop = (VENV_DIR / "Lib/site-packages/PySide6").exists() or any(
        VENV_DIR.glob("lib/python*/site-packages/PySide6"))
    names = [f"{base}{suffix}" for _dir, _entry, base, _help in LAUNCHER_SPECS
             for suffix in ((".ps1", ".bat") if WINDOWS else (".sh",))]
    return {"venv": VENV_PYTHON.exists(), "desktop": desktop, "running": _tray_running(),
            "launchers": sum((ROOT / name).exists() for name in names), "launchers_total": len(names)}


def settings_rows(current, choices) -> None:
    """The choices setup makes, with their values; a changed value is marked."""
    def mark(changed: bool) -> str:
        return "  (changed)" if changed else ""
    libraries = "; ".join(choices.libraries) or "none yet: choose one in Customize"
    row("Library folders", libraries + mark(choices.libraries != current.libraries),
        "text" if choices.libraries else "warning")
    row("Web view", _web_words(choices.web) + mark(choices.web != current.web))
    if choices.start_at_login is None:
        row("Start at sign-in", "not available on this system", "detail")
    else:
        row("Start at sign-in", ("on" if choices.start_at_login else "off")
            + mark(choices.start_at_login != current.start_at_login))
    if current.clients or choices.git_client:
        row("Desktop Git app", _client_words(current, choices.git_client)
            + mark(choices.git_client != current.git_client))
    else:
        row("Desktop Git app", "none found. Optional: Sourcetree or GitHub Desktop, to open a "
            "repository from the map.", "detail")
    fleet_changed = choices.fleet_mode != "keep" and (choices.fleet_mode != "none" or bool(current.fleet_transports))
    row("Fleet", _fleet_words(current, choices) + mark(fleet_changed))


def _protected_words(current, choices) -> str:
    anywhere = len(current.protected.get("never_publish", []))
    words = len(current.protected.get("never_publish_words", []))
    text = f"{anywhere + words}" + (f" ({words} whole word only)" if words else "")
    return text + (f"; {len(choices.protect)} to add" if choices.protect else "")


def _scanner_words(current) -> tuple[str, str]:
    from Special._settings import SECURITY_ENGINES
    installed = [name for name in SECURITY_ENGINES if current.tools.get(name)]
    if current.engines:
        return "built-in checks, plus " + ", ".join(current.engines), "success"
    if installed:
        return f"built-in checks; {', '.join(installed)} installed, not selected", "text"
    return ("built-in checks. Optional: gitleaks, betterleaks or trufflehog add deeper credential "
            "scanning."), "text"


def feature_rows(current, choices, install) -> None:
    """Every feature and integration, one row each, in words. Optional ones say what they add."""
    tools, transports = current.tools, current.fleet_transports
    section("This computer")
    row("Computer", current.machine or socket.gethostname())
    if tools.get("git"):
        row("Requirements", "ready (Git and Python found)", "success")
    else:
        row("Requirements", "Git is missing. Get it at git-scm.com, then run setup again.", "error")
    if install["running"]:
        row("Desktop app", "running in the tray", "success")
    elif install["desktop"]:
        row("Desktop app", "installed, not running", "text")
    elif install["venv"] and not tools.get("uv"):
        row("Desktop app", "needs uv to install (docs.astral.sh/uv); the command-line tools work "
            "without it", "warning")
    else:
        row("Desktop app", "not installed yet; setup installs it in this folder", "warning")
    have = install["launchers"] == install["launchers_total"]
    row("Tool shortcuts", "in this folder: double-click gitspecops-tray to start the app; the "
        "others open a tool" if have else "not made yet; setup puts them in this folder",
        "text" if have else "warning")

    section("Your setup" if current.enrolled else "Recommended setup")
    settings_rows(current, choices)

    section("Protection")
    row("Publish checks", "on: a checked commit or push holds anything protected", "success")
    row("Protected values", _protected_words(current, choices))
    scanners, tone = _scanner_words(current)
    row("Credential scans", scanners, tone)

    section("Integrations")
    if current.github:
        row("GitHub", "signed in" + ("; the fleet keeps status in a private repository" if "repo" in transports
                                     else ""), "success")
    elif tools.get("gh"):
        row("GitHub", "gh found, not signed in. Optional: run gh auth login for GitHub work.", "detail")
    else:
        row("GitHub", "gh not installed. Optional: organization copies, archive sync, publishing.", "detail")
    if current.tailnet:
        row("Tailscale", "connected" + ("; your fleet talks over it" if "tailnet" in transports
                                        else "; no fleet uses it yet"), "success")
    else:
        row("Tailscale", "not connected. Optional: your machines talk to each other directly.", "detail")
    if transports.get("folder"):
        row("Synced folder", "your fleet shares through " + _short(transports["folder"].get("path", "")), "success")
    elif current.synced_folders:
        row("Synced folder", ", ".join(Path(f).name for f in current.synced_folders) + " found; no fleet uses it",
            "text")
    else:
        row("Synced folder", "none found. Optional: OneDrive, Dropbox, Google Drive or Nextcloud can "
            "carry fleet status.", "detail")
    if current.archives is None:
        row("Archive copies", "could not be read; see Detection details", "warning")
    elif current.archives:
        task = {True: "monthly refresh scheduled", False: "no scheduled refresh",
                None: "refresh schedule not checked"}[current.archive_task]
        row("Archive copies", f"{current.archives} registered; {task}", "success" if current.archive_task else "text")
    else:
        row("Archive copies", "none. Optional: full copies of a GitHub organization, kept current "
            "(manage-archives).", "detail")


# --- the screens ---------------------------------------------------------------------
def start_screen(current, choices, pending: int) -> str:
    install = install_state()
    git_found = bool(current.tools.get("git", shutil.which("git")))
    menu_header("Setup")
    if not git_found:
        notice("Needs attention", "Git is required. Install it from https://git-scm.com/downloads, "
               "then run setup again.", "warning")
    elif current.enrolled:
        notice("gitSpecOps is set up on this computer", "Change your setup, repair it, or uninstall.", "success")
    else:
        notice("Ready to install", "This computer has what gitSpecOps needs. Nothing changes until "
               "you review and confirm.", "success")
    feature_rows(current, choices, install)
    if pending:
        notice(f"{pending} change{'s' if pending != 1 else ''} waiting", "Review and apply them, or exit "
               "to discard them.", "warning")
    say()
    keys = "0dm"
    if git_found:
        option("1", "Review and apply" if current.enrolled else "Review setup",
               "" if (pending or not current.enrolled) else "Nothing changed: re-checks and repairs this folder.")
        option("2", "Customize")
        keys += "12"
        if current.enrolled:
            option("U", "Uninstall gitSpecOps", "Opens the removal screen. Your repositories and settings are kept.")
            keys += "u"
    option("D", "Detection details")
    option("M", "More tools", "Updater preferences and older settings.")
    option("0", "Exit without changes" if current.enrolled else "Exit without installing")
    return choose(keys, "1" if git_found else "0")


def customize(current, choices):
    """Every choice separate; edits are kept only with [A]."""
    working = copy.deepcopy(choices)
    while True:
        menu_header("Customize")
        say()
        line("Choose an option to change it. Nothing is saved yet.")
        say()
        settings_rows(current, working)
        row("Protected values", _protected_words(current, working))
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
    menu_header("Review setup")
    say()
    blockers = problems(current, choices)
    install = needs_install(current, changes)
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
    if install or changes:
        line("For your account only, in this folder; no administrator rights.")
    line("Not changed: your repositories, your files, and anything else on this computer.")
    if blockers:
        say()
        for text in blockers:
            line(text, "warning")
    say()
    keys, apply = "b0", ("a" if current.enrolled else "i")
    if not blockers and (install or changes):
        option(apply.upper(), "Apply" if current.enrolled else "Install")
        keys += apply
    option("B", "Back")
    option("0", "Cancel")
    answer = choose(keys, "0")
    return "i" if answer == apply else answer


def needs_install(current, changes) -> list[str]:
    """The install part of the run, in review words: a first setup installs; an installed
    computer with nothing else to change re-checks and repairs this folder."""
    if not (current.enrolled and VENV_PYTHON.exists()):
        return ["Launchers in this folder and its Python environment (.venv), with the desktop app; "
                "nothing installed elsewhere."]
    if not changes:
        return ["Re-check the launchers and the Python environment in this folder; rewrite or rebuild "
                "anything missing."]
    return []


def apply_plan(current, choices, changes) -> bool:
    """The run screen: install steps, then every planned change, numbered and timed."""
    run_header("Installing" if not current.enrolled else "Applying",
               f"everything on the review  |  folder: {_short(str(ROOT))}  |  settings: {_short(current.settings_file)}")
    install = bool(needs_install(current, changes))
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
    menu_header("Uninstall")
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
    option("R", "Remove gitSpecOps from this computer")
    option("0", "Cancel")
    if choose("r0", "0") != "r":
        return
    run_header("Uninstalling", f"the sign-in entry, the launchers and .venv  |  folder: {_short(str(ROOT))}")
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
    install = install_state()
    menu_header("Detection details")
    section("This computer")
    row("Computer", socket.gethostname())
    row("Python", f"{platform.python_version()}  {sys.executable}")
    row("Environment", str(VENV_DIR) if install["venv"] else "not built")
    row("Desktop app", "Qt (PySide6) installed in .venv" if install["desktop"] else "Qt (PySide6) not installed")
    row("Tool shortcuts", f"{install['launchers']} files in {ROOT}")
    row("Settings file", current.settings_file)
    row("Start at sign-in", current.login_target or ("off" if current.start_at_login is False else "not available"))
    row("Web view", f"port {current.local_port} on this computer"
        + ("; tray answering" if install["running"] else "; not answering"))
    section("Programs on PATH")
    from Elaborate._fleet.setup_plan import TOOLS
    for name in TOOLS:
        path = current.tools.get(name, "")
        row(name, path or ("not found: required" if name == "git" else "not found (optional)"),
            "text" if path else ("error" if name == "git" else "detail"))
    row("GitHub sign-in", "signed in" if current.github else "not signed in", "text" if current.github else "detail")
    section("Fleet")
    if current.fleet_transports:
        for name, entry in current.fleet_transports.items():
            detail = entry.get("path") or entry.get("name") or (f"port {entry['port']}" if "port" in entry else "")
            row(name, detail + (f", every {entry['seconds']} s" if entry.get("seconds") else ""))
        row("Shares names", "yes" if current.share_names else "no")
    else:
        row("Fleet", "this computer only")
    row("Synced folders", ", ".join(current.synced_folders) or "none found")
    section("Protection")
    for name, values in sorted(current.protected.items()):
        row(name.replace("_", " "), f"{len(values)} {'entry' if len(values) == 1 else 'entries'}")
    row("Scanners selected", ", ".join(current.engines) or "built-in checks only")
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
