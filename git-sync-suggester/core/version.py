"""What version this is, and whether a newer release exists.

The number is written down once, in `pyproject.toml`, and read from there -- it used to be
typed into this module as well, with a test whose only job was catching the two drifting apart.
A frozen build carries `pyproject.toml` beside its modules (see the PyInstaller recipe).

The release check is **read-only and offline-safe**. It asks GitHub for the latest release and
reports; it never downloads, replaces or restarts anything. Every failure -- no network, no
`gh`, rate limited, no releases yet -- is "unknown", never an error and never "up to date".
A source checkout is told to `git pull`, never mutated.

Lives with Sync Suggester because only its modules use it; phase 3c settles its final home.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from Basic._providers.github import latest_release_tag

PRODUCT_NAME = "gitSpecOps"
REPOSITORY = "sb4ssman/gitSpecOps"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
UNKNOWN = "unknown"


def running_from_source() -> bool:
    """A frozen bundle is replaced by downloading a release; a checkout is updated with git."""
    return not getattr(sys, "frozen", False)


def _pyproject() -> Path:
    if running_from_source():
        return Path(__file__).resolve().parents[2] / "pyproject.toml"
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "pyproject.toml"


def read_version(path: Path | None = None) -> str:
    """The `[project] version` from pyproject.toml, or "unknown" when it cannot be read."""
    try:
        data = tomllib.loads((path or _pyproject()).read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return UNKNOWN


VERSION = read_version()


def _parts(version: str) -> tuple:
    """Compare released versions numerically; a tag we cannot parse sorts as older."""
    cleaned = version.strip().lstrip("vV").split("+")[0].split("-")[0]
    numbers = []
    for chunk in cleaned.split("."):
        if not chunk.isdigit():
            return (0,)
        numbers.append(int(chunk))
    return tuple(numbers) or (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return _parts(candidate) > _parts(current)


def latest_release(timeout: int = 15) -> str | None:
    """The newest published release tag, or None when that cannot be determined."""
    return latest_release_tag(REPOSITORY, timeout)


def check_for_update(timeout: int = 15) -> dict:
    """Report-only update status. Never raises; 'unknown' is a first-class answer.

    The broad except is deliberate: a convenience check must never take down the command the
    user actually ran.
    """
    try:
        latest = None if VERSION == UNKNOWN else latest_release(timeout)
    except Exception:  # noqa: BLE001 - an update check may never crash its caller
        latest = None
    if latest is None:
        return {"current": VERSION, "latest": None, "state": "unknown",
                "message": "Could not check for updates (no network, no gh login, or no "
                           "release published yet).", "url": RELEASES_URL}
    if is_newer(latest, VERSION):
        how = ("git pull" if running_from_source()
               else f"download the new build from {RELEASES_URL}")
        return {"current": VERSION, "latest": latest, "state": "outdated",
                "message": f"{PRODUCT_NAME} {latest} is available (you have {VERSION}) — {how}.",
                "url": RELEASES_URL}
    return {"current": VERSION, "latest": latest, "state": "current",
            "message": f"{PRODUCT_NAME} {VERSION} is up to date.", "url": RELEASES_URL}


def version_line() -> str:
    origin = "source" if running_from_source() else "bundle"
    return f"{PRODUCT_NAME} {VERSION} ({origin})"
