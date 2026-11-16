"""Start the app on its own: no console window, and not tied to whatever started it.

Why:          started from setup or a terminal, the app closed when that window closed (node1,
              2026-11-15, twice). Setup runs inside `uv run`, and Windows Terminal (Windows 11's
              default) can end what a closed tab started even when it was detached. On Windows the
              app is therefore started by Windows itself (WMI's Win32_Process.Create): its parent
              is a Windows service, never setup, a terminal or `gitso tray`, so no window closing
              can take it down. Checked on a test process under `uv run`: desktop session, no job,
              no console, still running after its starter ended.
Reads:        whether the app already holds its lock (one tray per profile).
May change:   starts the tray as a separate process.
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
# Windows fallback: leave the caller's job (uv run's), its console, and its Ctrl+C group.
_BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
# Windows starts the process from its WMI service; the command line and folder go through the
# environment, so no quoting reaches PowerShell.
_WMI_START = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              "@{CommandLine=$env:GITSO_START; CurrentDirectory=$env:GITSO_START_IN}; "
              "if ($r.ReturnValue -eq 0) { $r.ProcessId } else { exit 1 }")
STARTED = "started on its own: its icon is by the clock (Windows may tuck it under the ^ arrow)"
ALREADY = "already running: its icon is by the clock (Windows may tuck it under the ^ arrow)"


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


def _through_windows(argv: list[str]) -> int | None:
    """Ask Windows (WMI) to start `argv`; its process id, or None when that was refused."""
    if any(name.startswith("GITSPECOPS_") for name in os.environ):
        return None  # WMI gives the new process the user's own environment; keep these overrides
    try:
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _WMI_START],
                              env={**os.environ, "GITSO_START": subprocess.list2cmdline(argv),
                                   "GITSO_START_IN": str(ROOT)},
                              capture_output=True, text=True, timeout=60,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip()
    return int(text) if done.returncode == 0 and text.isdigit() else None


def _exit_code(pid: int, wait: float) -> int | None:
    """Wait up to `wait` seconds for process `pid`: its exit code, or None while it runs."""
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
    if not handle:
        return None if running() else 1  # gone before it could be asked: the lock says which
    try:
        if kernel.WaitForSingleObject(handle, int(wait * 1000)) != 0:  # not WAIT_OBJECT_0: running
            return None
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value
    finally:
        kernel.CloseHandle(handle)


def _popen(argv: list[str]) -> subprocess.Popen:
    common = {"cwd": ROOT, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name != "nt":
        return subprocess.Popen(argv, start_new_session=True, **common)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(argv, creationflags=flags | _BREAKAWAY, **common)
    except OSError:  # a job that refuses breakaway: start it anyway, inside that job
        return subprocess.Popen(argv, creationflags=flags, **common)


def start(arguments: list[str] | None = None, *, wait: float = 5.0) -> str:
    """Start the tray on its own with `arguments`, then make sure it is still running."""
    if running():
        return ALREADY
    argv = [str(interpreter()), str(TRAY), "--foreground", *(arguments or [])]
    pid = _through_windows(argv) if os.name == "nt" else None
    if pid is not None:
        code = _exit_code(pid, wait)
    else:
        process = _popen(argv)
        try:
            code = process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            code = None
    if code is None:
        return STARTED
    if code == 0:
        return ALREADY
    raise RuntimeError(f"the app stopped at once (exit code {code}); run gitso tray --foreground to see why")
