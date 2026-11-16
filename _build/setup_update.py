"""Update gitSpecOps in place, keeping every setting: fetch, fast-forward, refresh what depends on it.

Why:          after the first setup, updating should be one step that changes nothing already
              chosen (the user, 2026-11-15), not a walkthrough again.
Reads:        this folder's Git state: its branch, its upstream, uncommitted changes, what is new.
May change:   only after a yes: this folder fast-forwarded to its upstream; then, from the new
              code, the desktop app's Qt (when installed) and the gitso launchers (when present).
              Never a setting, a library, the fleet, protected values or a repository.
Results:      the screens; exit 0 when up to date or updated, 1 when it could not.
Layer:        setup (_build).
Status:       working

It refuses rather than guesses: uncommitted changes in this folder, no upstream, or commits here
that the upstream does not have (not a fast-forward) each stop it with what to do instead.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Basic._station import banner, bullet, choose, line, notice, option, say  # noqa: E402

VENV = ROOT / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          errors="replace", timeout=timeout)


def update(answer=None) -> int:
    """The express update. `answer` stands in for the person's choice (tests)."""
    banner("Setup  /  Update gitSpecOps", tagline=True)
    say()
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        notice("Not updated", "This folder has changes of its own. Commit them or put them aside, then "
               "update. Nothing was changed.", "warning")
        return 1
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if upstream.returncode != 0:
        notice("Not updated", f"This folder's branch ({branch}) follows no branch on GitHub, so there is "
               "nothing to update from. Nothing was changed.", "warning")
        return 1
    line(f"Checking GitHub for a newer gitSpecOps ({upstream.stdout.strip()})...", "detail")
    fetched = git("fetch", "--quiet")
    if fetched.returncode != 0:
        notice("Not updated", "GitHub could not be reached: " + (fetched.stderr.strip().splitlines() or
                                                                  ["no answer"])[-1], "warning")
        return 1
    ahead = int(git("rev-list", "--count", "@{u}..HEAD").stdout.strip() or 0)
    behind = int(git("rev-list", "--count", "HEAD..@{u}").stdout.strip() or 0)
    if ahead:
        notice("Not updated", f"This folder has {ahead} commit(s) GitHub does not, so updating is not a "
               "simple step forward. Nothing was changed.", "warning")
        return 1
    if not behind:
        notice("Up to date", f"gitSpecOps is current ({git('log', '-1', '--format=%h %s').stdout.strip()}).",
               "success")
        # The folder can be current while the running app is not (it started before the folder
        # moved forward): restart it, so what you see is what is here (the user, 2026-11-16).
        if _app_running() and _app_commit() != git("rev-parse", "HEAD").stdout.strip():
            line("The running app is an older version than this folder: restarting it...", "detail")
            if not _stop_app():
                notice("Not restarted", "The app did not stop within 15 seconds; quit it from its tray "
                       "menu, then run gitso tray.", "warning")
                return 1
            _start_app()
        return 0
    line(f"{behind} new change(s):", "text")
    for entry in git("log", "--format=%h %s", "-n", "15", "HEAD..@{u}").stdout.splitlines():
        bullet(entry)
    if behind > 15:
        bullet(f"... and {behind - 15} more")
    say()
    line("Your settings, libraries, fleet and protected values stay exactly as they are.", "muted")
    option("U", "Update")
    option("0", "Cancel", "Nothing has been changed.")
    if (answer or choose("u0", "u")) != "u":
        notice("Cancelled", "Nothing has been changed.", "warning")
        return 0
    # A running app keeps the old code until it restarts, and on Windows it holds files the update
    # may replace: stop it first, start it again afterwards (the user, 2026-11-16).
    was_running = _app_running()
    if was_running:
        line("Stopping the app for the update...", "detail")
        if not _stop_app():
            notice("Not updated", "The app did not stop within 15 seconds. Quit it from its tray menu, then "
                   "update again. Nothing was changed.", "warning")
            return 1
    moved = git("merge", "--ff-only", "@{u}")
    if moved.returncode != 0:
        notice("Not updated", "The fast-forward did not apply: " + (moved.stderr.strip().splitlines() or
                                                                    ["unknown reason"])[-1], "error")
        if was_running:
            _start_app()
        return 1
    line(f"Updated to {git('log', '-1', '--format=%h %s').stdout.strip()}.", "success")
    # What depends on the code is refreshed by the new code, in a new process.
    python = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    code = subprocess.call([str(python), str(ROOT / "_build" / "setup_gitspecops.py"), "refresh"], cwd=ROOT)
    if was_running:
        line("Starting the app again, with the new version...", "detail")
        _start_app()
    return code


def _app_running() -> bool:
    try:
        from App._detach import running
        return running()
    except Exception:  # noqa: BLE001 - no app here: nothing to stop
        return False


def _app_commit() -> str:
    """The commit the running app started from; "" when it did not say (an app older than this)."""
    import json
    try:
        from Special._settings.fleet import fleet_directory
        return str(json.loads((fleet_directory() / "tray-process.json").read_text()).get("commit") or "")
    except Exception:  # noqa: BLE001 - unknown: treated as older, so it is restarted
        return ""


def _stop_app() -> bool:
    from App._tray.control import request_stop
    return request_stop()


def _start_app() -> None:
    """Started by the new code, in a new process, on its own (App/_detach.py)."""
    python = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    subprocess.call([str(python), str(ROOT / "gitso.py"), "tray"], cwd=ROOT)


def main(argv=None) -> int:
    """`gitso update`: the same update as setup's menu item 2. --yes updates without asking."""
    import argparse
    parser = argparse.ArgumentParser(prog="gitso update", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--yes", action="store_true", help="update without asking (it still shows what is new)")
    args = parser.parse_args(argv)
    return update("u" if args.yes else None)


def refresh() -> int:
    """After an update: refresh the desktop app's Qt and the gitso launchers, where present."""
    say()
    done, failed = [], []
    has_qt = (VENV / "Lib/site-packages/PySide6").exists() or any(VENV.glob("lib/python*/site-packages/PySide6"))
    uv = shutil.which("uv")
    if has_qt and uv:
        from Elaborate._fleet.sealed import sync_extras  # keeps Qt, and encryption when installed
        if subprocess.call([uv, "sync", *sync_extras()], cwd=ROOT) == 0:
            done.append("desktop app: Qt as this version expects")
        else:
            failed.append("desktop app: uv sync did not finish (setup's desktop app part repairs it)")
    elif has_qt:
        failed.append("desktop app: uv is not on PATH, so Qt was not refreshed")
    from _build import gitso_command
    if gitso_command.status()["launcher"] == "here":
        try:
            gitso_command.install_launchers()
            done.append("gitso command: launchers rewritten for this version")
        except OSError as exc:
            failed.append(f"gitso command: {exc}")
    for item in done:
        bullet(item)
    for item in failed:
        bullet(item, "warning")
    try:
        from App._detach import running
        if running():
            line("The app is running the old version: quit it from its tray menu, then run gitso tray.",
                 "warning")
    except Exception:  # noqa: BLE001 - only advice; never fail an update over it
        pass
    notice("Update complete" if not failed else "Updated, with notes above",
           "Nothing you chose was changed.", "success" if not failed else "warning")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
