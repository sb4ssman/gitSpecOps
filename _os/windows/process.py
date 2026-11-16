"""Windows: stop a command together with everything it started.

Killing only the direct child is not enough here. The virtual environment's `python.exe` and
Git for Windows' `cmd\\git.exe` are launchers that run the real program as a *child*; kill the
launcher and the real program lives on, still holding the output pipe open, so the caller's
read after a timeout never returns -- a timeout that hangs. `taskkill /T` ends the whole tree.
"""
from __future__ import annotations

import subprocess


def _has_console() -> bool:
    """Whether this process has a console window: a terminal, yes; the tray or a scheduled task
    (pythonw.exe), no."""
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except (ImportError, OSError, AttributeError):
        return True  # cannot tell: behave as before


def spawn_options() -> dict:
    """Extra `Popen` arguments for every program gitSpecOps starts.

    Without a console of its own (the tray, a scheduled task), Windows gives each console
    program it starts -- every git call -- a new window that takes the keyboard. Scanning a
    library makes hundreds a minute and the computer cannot be used (2026-11-15). So with no
    console, programs start with no window; their output still comes back through the pipes.
    From a terminal, programs share that terminal, as before."""
    if _has_console():
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def window_options() -> dict:
    """For a `subprocess.run` outside `Basic._run`: no window without a console (spawn_options)."""
    return spawn_options()


def stdin_is_interactive() -> bool:
    """True only when stdin is a real console. `isatty()` is not enough on Windows: it answers
    True for the `NUL` device, which is what a scheduled or detached run is given, and a command
    that believes a person is there would open a dialog nobody can see."""
    try:
        import ctypes
        import msvcrt
        mode = ctypes.c_uint32()
        handle = msvcrt.get_osfhandle(0)
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (ImportError, OSError, ValueError, AttributeError):
        return False


def kill_tree(proc: subprocess.Popen) -> None:
    """End proc and all of its descendants. Never raises."""
    if proc.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
