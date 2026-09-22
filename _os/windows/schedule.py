"""Windows: scheduled runs are Task Scheduler tasks, managed through `schtasks`.

Every task runs as the interactive user who created it -- never as a service -- so the user's
own `git` credentials, `gh` login and file ownership apply. Output is left on the console so
the person creating or inspecting a task sees exactly what Task Scheduler said.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

SUPPORTED = True
_TIMEOUT = 60


def _schtasks(*args: str) -> int:
    try:
        return subprocess.run(["schtasks", *args], text=True, timeout=_TIMEOUT).returncode
    except FileNotFoundError:
        print("schtasks was not found on this system.")
        return 127
    except subprocess.TimeoutExpired:
        print(f"schtasks did not answer within {_TIMEOUT}s.")
        return 124


def install_monthly(task_name: str, command: Path, day: int, time_of_day: str) -> int:
    """Create or replace a monthly task that runs `command`. Returns schtasks' exit code."""
    return _schtasks("/Create", "/TN", task_name, "/TR", str(command), "/SC", "MONTHLY",
                     "/D", str(day), "/ST", time_of_day, "/F")


def status(task_name: str) -> int:
    """Print the task's details. Read-only."""
    return _schtasks("/Query", "/TN", task_name, "/V", "/FO", "LIST")


def remove(task_name: str) -> int:
    """Delete the task."""
    return _schtasks("/Delete", "/TN", task_name, "/F")
