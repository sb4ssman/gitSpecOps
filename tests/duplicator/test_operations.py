"""The duplicator's per-repository operations never delete a folder they did not create.

Offline: `run_checked` (every git call), repository creation and logging are faked, so no
network, no GitHub and no real repository is involved. The fake "clone" creates the folder git
would create, which is what the cleanup paths act on.

The bug this pins (2026-10-19): download and migrate both began by deleting any folder already
at the destination path, as a "leftover". A folder the user made is not a leftover.
"""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic._run import Result  # noqa: E402
from Special.duplicate_org import _operations as ops  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


class FakeGit:
    """Plays `git clone`: creates the destination as a repository, optionally failing first."""

    def __init__(self, fail_first: int = 0):
        self.fail_first, self.calls = fail_first, []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[:2] == ["git", "clone"]:
            target = Path(argv[-1])
            (target / ("objects" if "--mirror" in argv else ".git")).mkdir(parents=True)
            if "--mirror" in argv:
                (target / "refs").mkdir()
                (target / "HEAD").write_text("ref: refs/heads/main\n")
            if self.fail_first:
                self.fail_first -= 1
                raise RuntimeError("Command failed: git clone\nfatal: early EOF")
        if "for-each-ref" in argv:
            return Result(argv, 0, "refs/heads/main\nrefs/pull/1/head\n", "")
        return Result(argv, 0, "", "")


def run_quietly(call):
    with redirect_stdout(io.StringIO()):
        return call()


original = (ops.run_checked, ops.create_repo, ops.log_message, ops._retry_backoff)
ops.create_repo = lambda *a, **k: None
ops.log_message = lambda *a, **k: None
ops._retry_backoff = lambda attempt: 0
try:
    with tempfile.TemporaryDirectory(prefix="dup-ops-") as tmp:
        tmp = Path(tmp)
        logs = [str(tmp / name) for name in ("done.txt", "ok.log", "err.log")]

        for mirror in (False, True):
            label = "mirror" if mirror else "working"
            dest = tmp / f"dest-{label}"
            dest.mkdir()
            folder = dest / ("tool.git" if mirror else "tool")
            (folder / "config").mkdir(parents=True)  # an ordinary project, not a repository
            (folder / "precious.txt").write_text("exists nowhere else\n", encoding="utf-8")
            fake = ops.run_checked = FakeGit()
            result = run_quietly(lambda: ops.download_single_repo(
                {"name": "tool"}, 1, 1, "example-org", str(dest), mirror, *logs))
            check(f"download ({label}) over an existing folder fails",
                  result["status"] == "failed")
            check(f"download ({label}) leaves the existing folder untouched",
                  (folder / "precious.txt").exists())
            check(f"download ({label}) never starts a clone over it", fake.calls == [])

        # An empty folder the user made in advance is a destination, not an obstacle: git
        # itself clones into an existing empty folder. It must still be there after a failure.
        for mirror in (False, True):
            label = "mirror" if mirror else "working"
            dest = tmp / f"dest-empty-{label}"
            empty = dest / ("tool.git" if mirror else "tool")
            empty.mkdir(parents=True)
            ops.run_checked = FakeGit()
            result = run_quietly(lambda: ops.download_single_repo(
                {"name": "tool"}, 1, 1, "example-org", str(dest), mirror, *logs))
            check(f"download ({label}) into an empty folder the user made succeeds",
                  result["status"] == "success" and any(empty.iterdir()))
            dest = tmp / f"dest-empty-fails-{label}"
            empty = dest / ("tool.git" if mirror else "tool")
            empty.mkdir(parents=True)
            ops.run_checked = FakeGit(fail_first=ops.RETRY_ATTEMPTS)
            result = run_quietly(lambda: ops.download_single_repo(
                {"name": "tool"}, 1, 1, "example-org", str(dest), mirror, *logs))
            check(f"a failed download ({label}) leaves the user's empty folder in place, empty",
                  result["status"] == "failed" and empty.is_dir() and not any(empty.iterdir()))

        # A half-finished clone has a .git, so the next batch run would count it as downloaded
        # and skip it for good. A failed download must leave nothing behind.
        dest = tmp / "dest-gives-up"
        dest.mkdir()
        ops.run_checked = FakeGit(fail_first=ops.RETRY_ATTEMPTS)
        result = run_quietly(lambda: ops.download_single_repo(
            {"name": "tool"}, 1, 1, "example-org", str(dest), False, *logs))
        check("a download that gives up leaves no half-clone to be mistaken for a finished one",
              result["status"] == "failed" and not (dest / "tool").exists())

        dest = tmp / "dest-retry"
        dest.mkdir()
        fake = ops.run_checked = FakeGit(fail_first=1)
        result = run_quietly(lambda: ops.download_single_repo(
            {"name": "tool"}, 1, 1, "example-org", str(dest), False, *logs))
        check("a clone this run left half-done is cleaned up and retried",
              result["status"] == "success" and len(fake.calls) == 2
              and (dest / "tool" / ".git").is_dir())

        work = tmp / "migrate-work"
        work.mkdir()
        mine = work / "tool"
        mine.mkdir()
        (mine / "precious.txt").write_text("exists nowhere else\n", encoding="utf-8")
        fake = ops.run_checked = FakeGit()
        result = run_quietly(lambda: ops.process_migrate_repo(
            {"name": "tool", "isPrivate": True}, "example-org", "example-dest", str(work), *logs))
        check("migrate over an existing folder fails", result.get("status") == "failed")
        check("migrate leaves the existing folder untouched", (mine / "precious.txt").exists())
        check("migrate never clones or pushes over it", fake.calls == [])

        prepared = tmp / "migrate-prepared"
        (prepared / "tool").mkdir(parents=True)
        ops.run_checked = FakeGit()
        result = run_quietly(lambda: ops.process_migrate_repo(
            {"name": "tool", "isPrivate": True}, "example-org", "example-dest", str(prepared),
            *logs))
        check("migrate through an empty folder the user made succeeds and leaves it empty",
              result.get("status") == "success" and (prepared / "tool").is_dir()
              and not any((prepared / "tool").iterdir()))

        fresh = tmp / "migrate-fresh"
        fresh.mkdir()
        fake = ops.run_checked = FakeGit()
        result = run_quietly(lambda: ops.process_migrate_repo(
            {"name": "tool", "isPrivate": True}, "example-org", "example-dest", str(fresh), *logs))
        pushed = [c for c in fake.calls if "push" in c]
        check("migrate clones, pushes and removes only its own temporary mirror",
              result.get("status") == "success" and not (fresh / "tool").exists())
        check("migrate never pushes pull-request refs",
              pushed and all(not ref.startswith("refs/pull/") for ref in pushed[0][4:]))
finally:
    ops.run_checked, ops.create_repo, ops.log_message, ops._retry_backoff = original

# A real clone, not a fake: git writes object files read-only, which a plain `rmtree` cannot
# remove on Windows. Cleanup of this run's own clone must still succeed there.
import subprocess  # noqa: E402

from Special.duplicate_org._local_repos import safe_cleanup_directory  # noqa: E402

with tempfile.TemporaryDirectory(prefix="dup-real-") as tmp:
    parent = Path(tmp)
    seed = parent / "seed"
    subprocess.run(["git", "init", "-q", str(seed)], check=True)
    (seed / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(seed), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(seed), "-c", "user.name=T", "-c", "user.email=t@example.test",
                    "commit", "-q", "-m", "a"], check=True)
    subprocess.run(["git", "clone", "-q", "--mirror", str(seed), str(parent / "tool.git")],
                   check=True)
    with redirect_stdout(io.StringIO()):
        removed = safe_cleanup_directory(str(parent / "tool.git"), str(parent), "tool")
    check("a real mirror clone (read-only objects) is removed", removed
          and not (parent / "tool.git").exists())

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-DUPLICATOR-OPERATIONS-TESTS-PASS")
