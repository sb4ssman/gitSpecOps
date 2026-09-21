"""This machine's operating system, decided once, and its implementation of each OS component.

    from _os.current import paths
    paths.config_base()

`_os/windows/`, `_os/linux/` and `_os/macos/` each hold the same component files with the same
functions (`tests/os/test_os_parity.py` enforces it). Callers import the component from here
and never branch on the OS themselves. Where an OS has no mechanism yet, its file still exists
and says so, rather than being absent.

Rules for every file under `_os/`: stdlib only; import nothing from the layers; importable on
every OS (OS-only calls happen inside functions, never at import time).

Any POSIX system that is not macOS is treated as Linux.
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    NAME = "windows"
    from _os.windows import paths, process
elif sys.platform == "darwin":
    NAME = "macos"
    from _os.macos import paths, process
else:
    NAME = "linux"
    from _os.linux import paths, process

__all__ = ["NAME", "paths", "process"]
