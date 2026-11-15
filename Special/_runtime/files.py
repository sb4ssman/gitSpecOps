"""Caller-selected runtime destinations. Importing creates nothing; failures never fall back.

Enabled destinations may be created, but cannot live in this source checkout or traverse
existing links/reparse points. These checks are not an OS sandbox.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]


class RuntimeIOError(ValueError):
    """A stable code without a private path, value or subprocess diagnostic."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def linked(path: Path) -> bool:
    """Include Windows junctions on Python versions without Path.is_junction()."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) &
                                             getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def system_link(path: Path) -> bool:
    """A link the operating system made, not one planted to redirect a write: owned by root, in a
    folder owned by root that no one else can change. macOS's /var, /tmp and /etc (to /private/...)
    and a Linux /home -> /var/home are such links; a link any user could create never is."""
    if os.name != "posix":
        return False
    try:
        info, parent = path.lstat(), path.parent.lstat()
    except OSError:
        return False
    return (info.st_uid == 0 and parent.st_uid == 0
            and not parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def traverses_link(path: Path) -> bool:
    """Whether `path` or any folder above it is a link someone could have planted. Every check
    that walks a path's ancestry for links uses this, so they all agree."""
    return any(linked(part) and not system_link(part) for part in (path, *path.parents))


def checked_path(path: Path) -> Path:
    """Check lexical ancestry before following any existing filesystem links."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    if path == SOURCE_ROOT or SOURCE_ROOT in path.parents:
        raise RuntimeIOError("source_destination")
    if traverses_link(path):
        raise RuntimeIOError("linked_destination")
    return path


def prepare_directory(path: Path) -> Path:
    """Create only the selected destination; never choose another on failure."""
    path = checked_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    checked_path(path)
    if not path.is_dir():
        raise RuntimeIOError("invalid_destination")
    return path


def excluded(path: Path, exclusions, *, contains: bool = False) -> bool:
    """Match physical ancestry; contains also excludes a repo holding an excluded subtree."""
    resolved = path.resolve()
    return any(resolved == item.resolve() or item.resolve() in resolved.parents or
               (contains and resolved in item.resolve().parents) for item in exclusions)
