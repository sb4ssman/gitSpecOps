"""macOS: a command and its children share one process group; stopping it stops them all."""
from __future__ import annotations

from _os._posix import kill_tree, spawn_options

__all__ = ["kill_tree", "spawn_options"]
