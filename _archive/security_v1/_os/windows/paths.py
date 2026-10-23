"""Windows: per-user configuration lives under the roaming application-data folder."""
from __future__ import annotations

import os
from pathlib import Path


def config_base() -> Path:
    """`%APPDATA%`, or its usual location when the variable is missing."""
    return Path(os.environ.get("APPDATA") or "~/AppData/Roaming").expanduser()
