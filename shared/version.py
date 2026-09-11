"""The single source of truth for what version this checkout is, and whether it is current.

Before this existed the version was typed into two files that could disagree, there were no
tags, and no release to compare against -- so "am I up to date?" had no answer at all. Every
other piece of update machinery depends on that question being answerable first.

Deliberately modest, in the same spirit as the rest of the project:

- The check is **read-only**. It asks GitHub what the latest release is and reports. It never
  downloads, replaces, or restarts anything. A self-replacing binary is exactly the complexity
  that makes a tool need attention, and a broken self-update is the one bug that cannot fix
  itself.
- It is **opt-in and offline-safe**. Nothing here runs unless a command asks. Every failure --
  no network, no `gh`, rate limited, no releases yet -- returns "unknown", never an error and
  never a stall: an update check must never be the reason a status command fails.
- A **source checkout is told to `git pull`**, never mutated.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: Bump this, tag the commit `v<VERSION>`, and publish a GitHub release with that tag.
VERSION = "0.2.0"

PRODUCT_NAME = "gitSpecOps"
REPOSITORY = "sb4ssman/gitSpecOps"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"


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


def running_from_source() -> bool:
    """A frozen bundle is replaced by downloading a release; a checkout is updated with git."""
    return not getattr(sys, "frozen", False)


def latest_release(timeout: int = 15) -> str | None:
    """The newest published release tag, or None when that cannot be determined.

    Uses the `gh` CLI the project already depends on, so an update check introduces no new
    authentication and no new dependency. None means "unknown", which every caller must render
    as unknown rather than as "up to date" -- claiming current when we did not check is the
    same silence-as-good-news mistake the fleet rules exist to prevent.
    """
    try:
        proc = subprocess.run(
            ["gh", "release", "list", "--repo", REPOSITORY, "--limit", "1", "--json", "tagName"],
            capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode or not proc.stdout.strip():
        return None
    try:
        releases = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(releases, list) or not releases:
        return None
    tag = releases[0].get("tagName")
    return tag if isinstance(tag, str) and tag.strip() else None


def check_for_update(timeout: int = 15) -> dict:
    """Report-only update status. Never raises; 'unknown' is a first-class answer.

    The broad except is deliberate and is the whole point of this function: a convenience check
    must never be able to take down the command the user actually ran. `latest_release` guards
    the failures it can foresee; this guards the ones it cannot.
    """
    try:
        latest = latest_release(timeout)
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


def main() -> int:
    """Standalone: print the version, and the update status when asked."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from shared.console import enable_unicode_output

    enable_unicode_output()
    print(version_line())
    if "--check" in sys.argv[1:]:
        print(check_for_update()["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
