"""macOS: scheduled runs are not implemented yet; each call says so and returns 2."""
from __future__ import annotations

from _os._posix import install_monthly, remove, status

SUPPORTED = False

__all__ = ["SUPPORTED", "install_monthly", "remove", "status"]
