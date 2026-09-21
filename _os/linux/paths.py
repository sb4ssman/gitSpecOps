"""Linux: per-user configuration follows the XDG base-directory convention."""
from __future__ import annotations

import os
from pathlib import Path


def config_base() -> Path:
    """`$XDG_CONFIG_HOME`, else `~/.config`."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser()
