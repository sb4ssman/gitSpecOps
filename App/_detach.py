"""Start the app on its own: no console window, and not tied to whatever started it.

Why:          started from setup or a terminal, the app closed when that window closed (node1,
              2026-11-15). Setup runs inside `uv run`, and on Windows `uv run` ends everything it
              started when it exits; `gitso tray` ran the app inside the terminal's own process.
Reads:        whether the app already holds its lock (one tray per profile).
May change:   starts the tray as a separate process, detached from this one.
Results:      "started" or "already running"; RuntimeError when it stopped at once.
Layer:        App: presence. Setup's "Start the app" and `gitso tray` both come here.
Status:       working
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAY = ROOT / "App" / "tray.py"
# Windows: leave the caller's job (uv run's), its console, and its Ctrl+C group.
_BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB


def interpreter() -> Path:
    """This folder's windowless Python on Windows, its Python elsewhere; the running one if none."""
    scripts = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    for candidate in ((scripts / "pythonw.exe", Path(sys.executable).with_name("pythonw.exe"))
                      if os.name == "nt" else (scripts / "python",)):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def running(config_dir=None, settings_home=None) -> bool:
    """Whether a tray already holds this profile's lock. Only looks."""
    from Special._settings.fleet import fleet_directory
    from Special._sync.lock import TRAY_LOCK, app_lock
    try:
        directory = fleet_directory(config_dir, home=settings_home)
    except Exception:  # noqa: BLE001 - unreadable settings: the tray itself will say why
        return False
    if not (directory / TRAY_LOCK).exists():
        return False
    try:
        with app_lock(directory, TRAY_LOCK):
            return False
    except (ValueError, OSError):
        return True


def start(arguments: list[str] | None = None, *, wait: float = 5.0) -> str:
    """Start the tray detached with `arguments`, then make sure it is still running."""
    if running():
        return "already running: its icon is by the clock (Windows may tuck it under the ^ arrow)"
    argv = [str(interpreter()), str(TRAY), "--foreground", *(arguments or [])]
    common = {"cwd": ROOT, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(argv, creationflags=flags | _BREAKAWAY, **common)
        except OSError:  # a job that refuses breakaway: start it anyway, inside that job
            process = subprocess.Popen(argv, creationflags=flags, **common)
    else:
        process = subprocess.Popen(argv, start_new_session=True, **common)
    try:
        code = process.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        return "started: its icon is by the clock (Windows may tuck it under the ^ arrow)"
    if code == 0:
        return "already running: its icon is by the clock"
    raise RuntimeError(f"the app stopped at once (exit code {code}); run gitso tray --foreground to see why")
