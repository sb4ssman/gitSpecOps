"""What Linux and macOS genuinely share. Imported only by `_os/linux/` and `_os/macos/`."""
from __future__ import annotations

import os
import signal
import subprocess


def spawn_options() -> dict:
    """Start each command in its own session, so the command and its children form one group."""
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """End proc's whole process group (see `spawn_options`). Never raises."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, AttributeError):  # already gone, or no killpg on this platform
        pass
    try:
        proc.kill()
    except OSError:
        pass
