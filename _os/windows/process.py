"""Windows: stop a command together with everything it started.

Killing only the direct child is not enough here. The virtual environment's `python.exe` and
Git for Windows' `cmd\\git.exe` are launchers that run the real program as a *child*; kill the
launcher and the real program lives on, still holding the output pipe open, so the caller's
read after a timeout never returns -- a timeout that hangs. `taskkill /T` ends the whole tree.
"""
from __future__ import annotations

import subprocess


def spawn_options() -> dict:
    """Extra `Popen` arguments. Windows tracks the tree by parent id, so none are needed."""
    return {}


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
