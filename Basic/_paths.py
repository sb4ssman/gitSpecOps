"""Where gitSpecOps keeps per-user local state. Never inside the repository.

Everything a machine remembers -- fleet configuration, the local catalog, the archive registry
-- lives under one per-user folder, so a checkout can be deleted, moved or re-cloned without
losing it, and nothing personal can be committed by accident. The OS decides the base folder
(`_os/*/paths.py`); this module decides everything below it.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from _os.current import paths as _os_paths

APP_DIR_NAME = "gitSpecOps"


def config_home() -> Path:
    """The per-user gitSpecOps folder: `<OS config base>/gitSpecOps`.

    `GITSPECOPS_HOME` overrides it (tests, scratch runs), so nothing needs to touch the real one.
    """
    override = os.environ.get("GITSPECOPS_HOME")
    if override:
        return Path(override).expanduser()
    return _os_paths.config_base() / APP_DIR_NAME


def tools_home() -> Path:
    """Programs setup downloads because no package manager offers them here (a secret scanner):
    `~/.gitspecops/tools`, beside the gitso launchers. `GITSPECOPS_TOOLS` overrides it (tests)."""
    override = os.environ.get("GITSPECOPS_TOOLS")
    return Path(override).expanduser() if override else Path.home() / ".gitspecops" / "tools"


def find_program(name: str) -> str | None:
    """A program on PATH, or one setup downloaded into tools_home(); None when neither has it."""
    on_path = shutil.which(name)
    if on_path:
        return on_path
    downloaded = tools_home() / (name + (".exe" if os.name == "nt" else ""))
    return str(downloaded) if downloaded.is_file() else None


def sync_home() -> Path:
    """The fleet's runtime folder. `GITSPECOPS_SYNC_HOME` overrides everything (tests, scratch runs)."""
    override = os.environ.get("GITSPECOPS_SYNC_HOME")
    if override:
        return Path(override).expanduser()
    return config_home() / "fleet"
