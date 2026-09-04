"""Regression tests for cross-filesystem exclusion in repo discovery.

The bug these exist for, reported from a Windows machine on 2026-09-04: a `check` against
`T:\\Github\\...` returned an empty fleet. `os.DirEntry.stat()` on Windows serves data cached
from the directory scan, and that cached record carries `st_dev == 0`, while the root statted
directly reports a real device number. Every direct child therefore compared unequal and was
rejected as cross-filesystem, so the scan found nothing at all.

The rule that fixes it, and that these tests pin: exclude only on **positive evidence** of a
different filesystem. An unknown device id must never mean "skip".

Windows behaviour is reproduced here on any platform by wrapping `os.scandir` so entries
report the cached-zero device, which is the whole symptom.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared import repo_discovery  # noqa: E402
from shared.repo_discovery import device_id, entry_device_id, find_repos  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


class FakeEntry:
    """A scandir entry whose cached stat reports a device id, like Windows does."""

    def __init__(self, real, cached_dev):
        self._real, self._cached_dev = real, cached_dev
        self.name, self.path = real.name, real.path

    def is_dir(self, follow_symlinks=True):
        return self._real.is_dir(follow_symlinks=follow_symlinks)

    def stat(self, follow_symlinks=True):
        return SimpleNamespace(st_dev=self._cached_dev)


def scandir_reporting(cached_dev):
    """An os.scandir replacement whose entries report `cached_dev` from their cached stat."""
    real_scandir = repo_discovery.os.scandir

    def fake(path):
        return [FakeEntry(entry, cached_dev) for entry in real_scandir(path)]
    return fake


with tempfile.TemporaryDirectory(prefix="discovery-dev-") as tmp:
    tmp = Path(tmp)
    collection = tmp / "Github"
    for name in ("alpha-repo", "beta-repo", "gamma-repo"):
        repo = collection / name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True)

    baseline = find_repos(collection, max_depth=0)
    check(len(baseline) == 3, f"baseline discovery is broken before any faking: {baseline}")

    # --- the helpers ------------------------------------------------------------------
    check(device_id(collection) is not None, "a real directory should have a device id")
    check(device_id(tmp / "does-not-exist") is None,
          "a missing path should report an unknown device, not raise")
    real_entry = next(iter(os.scandir(collection)))
    check(entry_device_id(real_entry) is not None,
          "a normal entry should resolve a device id from its cached stat")
    check(entry_device_id(FakeEntry(real_entry, 0)) is not None,
          "a cached device of 0 must fall back to a real stat, not be taken literally")

    class Unstattable:
        name, path = "x", "/nonexistent/x"

        def stat(self, follow_symlinks=True):
            raise OSError("no")
    check(entry_device_id(Unstattable()) is None,
          "an entry that cannot be statted should report unknown, not raise")

    # --- the actual Windows symptom ---------------------------------------------------
    original = repo_discovery.os.scandir
    try:
        repo_discovery.os.scandir = scandir_reporting(0)
        windows_like = find_repos(collection, max_depth=0)
        check(len(windows_like) == 3,
              f"THE WINDOWS BUG: entries reporting a cached device of 0 were excluded, "
              f"found {len(windows_like)} of 3 repositories")
        check({Path(h.path).name for h in windows_like} ==
              {"alpha-repo", "beta-repo", "gamma-repo"},
              "the wrong repositories were returned under a cached-zero device")

        # A genuinely different device must still be excluded — the fix must not simply
        # disable the check.
        repo_discovery.os.scandir = scandir_reporting(999999)
        other_device = find_repos(collection, max_depth=0)
        check(other_device == [],
              f"a positively different device should still be excluded, got {other_device}")

        # ...unless the caller asked to cross filesystems.
        crossing = find_repos(collection, max_depth=0, cross_filesystems=True)
        check(len(crossing) == 3,
              f"cross_filesystems=True must ignore the device entirely, got {len(crossing)}")
    finally:
        repo_discovery.os.scandir = original

    check(len(find_repos(collection, max_depth=0)) == 3,
          "discovery did not return to normal after the fake was removed")

if failures:
    print("REPO-DISCOVERY-DEVICE-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-REPO-DISCOVERY-DEVICE-TESTS-PASS")
