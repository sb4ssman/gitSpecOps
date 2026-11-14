"""macOS: per-user configuration lives where Mac apps keep theirs, `~/Library/Application Support`."""
from __future__ import annotations

from pathlib import Path


def config_base() -> Path:
    """`~/Library/Application Support`."""
    return Path("~/Library/Application Support").expanduser()
