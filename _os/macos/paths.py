"""macOS: per-user configuration, XDG-style.

`~/Library/Application Support` is the native location. This keeps `~/.config` (honoring
`$XDG_CONFIG_HOME`) because that is where every earlier version looked on macOS; moving it is
a deliberate decision for when a Mac is actually validated, not a side effect of a refactor.
"""
from __future__ import annotations

import os
from pathlib import Path


def config_base() -> Path:
    """`$XDG_CONFIG_HOME`, else `~/.config`."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser()
