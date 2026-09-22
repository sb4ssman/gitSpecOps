"""Where gitSpecOps keeps per-user local state. Never inside the repository.

Everything a machine remembers -- fleet configuration, the local catalog, the archive registry
-- lives under one per-user folder, so a checkout can be deleted, moved or re-cloned without
losing it, and nothing personal can be committed by accident. The OS decides the base folder
(`_os/*/paths.py`); this module decides everything below it.
"""
from __future__ import annotations

import os
from pathlib import Path

from _os.current import paths as _os_paths

APP_DIR_NAME = "gitspecops"


def config_home() -> Path:
    """The per-user gitSpecOps folder: `<OS config base>/gitspecops`.

    `GITSPECOPS_HOME` overrides it (tests, scratch runs), so nothing needs to touch the real one.
    """
    override = os.environ.get("GITSPECOPS_HOME")
    if override:
        return Path(override).expanduser()
    return _os_paths.config_base() / APP_DIR_NAME


def sync_home() -> Path:
    """Sync Suggester's folder. `GITSPECOPS_SYNC_HOME` overrides everything (tests, scratch runs)."""
    override = os.environ.get("GITSPECOPS_SYNC_HOME")
    if override:
        return Path(override).expanduser()
    return config_home() / "sync-suggester"
