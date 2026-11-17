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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAY = ROOT / "App" / "tray.py"
# Windows fallback: leave the caller's job (uv run's), its console, and its Ctrl+C group.
_BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
# Windows starts the process from its WMI service; the command line and folder go through the
# environment, so no quoting reaches PowerShell.
# ShowWindow=0 (SW_HIDE): should the process get a console after all, its window is never shown
# (checked with a console Python, 2026-11-16: console present, window not visible).
_WMI_START = ("$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
              "-Property @{ShowWindow=[uint16]0}; "
              "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              "@{CommandLine=$env:GITSO_START; CurrentDirectory=$env:GITSO_START_IN; "
              "ProcessStartupInformation=$si}; "
              "if ($r.ReturnValue -eq 0) { $r.ProcessId } else { exit 1 }")


def where_the_icon_is() -> str:
    """Where to find the running app, said truthfully for this computer: a Mac too old for Qt
    runs it with no icon at all (macOS 10.15, 2026-11-16: "its icon is by the clock" was wrong)."""
    import importlib.util
    import sys
    try:
        has_qt = importlib.util.find_spec("PySide6") is not None
    except (ImportError, ValueError):
        has_qt = False
    if not has_qt:
        if sys.platform == "darwin":
            from App._tray.macos_bar import swift_compiler
            if swift_compiler():  # the native icon (App/_tray/macos_bar.py)
                return "its icon is in the menu bar"
        return "it has no icon on this computer (no Qt for it); open the page with gitso tray --open"
    if sys.platform == "darwin":
        return "its icon is in the menu bar"
    if os.name == "nt":
        return "its icon is by the clock (Windows may tuck it under the ^ arrow)"
    return "its icon is in the system tray"


STARTED = f"started on its own: {where_the_icon_is()}"
ALREADY = f"already running: {where_the_icon_is()}"


def interpreter() -> Path:
    """This folder's windowless Python on Windows, its Python elsewhere; the running one if none.
    The same one start-at-sign-in registers."""
    from Elaborate._fleet.autostart import app_interpreter
    return app_interpreter()


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


def _session_id() -> int | None:
    """This process's Windows session: 0 is the services session (SSH, services), which has no
    desktop; the signed-in person's desktop is 1 or higher."""
    import ctypes
    kernel = ctypes.windll.kernel32
    session = ctypes.c_ulong()
    return session.value if kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)) else None


def _through_desktop_session(argv: list[str]) -> bool:
    """From session 0, start `argv` in the signed-in person's desktop instead (2026-11-17: every app
    `gitso update` restarted over SSH ran in session 0, with no icon, holding the lock, so it looked
    dead until killed). A one-time task that runs only in that person's interactive session: made,
    run, deleted. Deleting it does not stop what it started. False when Windows refused."""
    if any(name.startswith("GITSPECOPS_") for name in os.environ):
        return False  # a task gets the person's own environment; keep these overrides
    # Inside a console with no window (2026-11-17): the virtual environment's pythonw.exe is a
    # launcher that starts the real python.exe, a console program, so a plain task opened a blank
    # console window on the desktop, and closing it killed the app. conhost --headless gives that
    # console no window at all (checked on Windows 10: "Window Title: N/A").
    conhost = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "conhost.exe"
    if not conhost.exists():
        return False
    command = subprocess.list2cmdline([str(conhost), "--headless", *argv])
    if len(command) > 261:  # schtasks' limit for the command
        return False
    name = f"gitSpecOps start {os.getpid()}"

    def schtasks(*args):
        return subprocess.run(["schtasks", *args], capture_output=True, text=True, timeout=60,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        if schtasks("/create", "/tn", name, "/tr", command, "/sc", "once", "/st", "23:59", "/it", "/f").returncode:
            return False
        return schtasks("/run", "/tn", name).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            schtasks("/delete", "/tn", name, "/f")
        except (OSError, subprocess.SubprocessError):
            pass


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
    # --detached: run in place, and give up any console this start gave it (App/_tray/qt.py).
    argv = [str(interpreter()), str(TRAY), "--detached", *(arguments or [])]
    if os.name == "nt" and _session_id() == 0 and _through_desktop_session(argv):
        # Started in the person's desktop: no process id comes back, so the lock says when it runs.
        import time
        for _ in range(int(max(wait, 1) * 4)):
            if running():
                return STARTED
            time.sleep(0.5)
        raise RuntimeError("the app did not start in your desktop session; is anyone signed in? "
                           "Start it there with gitso tray")
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
