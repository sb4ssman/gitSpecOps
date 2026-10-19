"""`fleet safe-to-wipe` may say SAFE only when nothing on this machine exists nowhere else.

Driven through the real command, end to end, on disposable libraries whose remotes are local
bare repositories (offline). Each at-risk case is built *alone* beside one clean, pushed
repository, so a pass cannot come from some other case tripping the verdict.

The bug this pins (2026-10-19): the command trusted the fleet observer's inventory, which drops
any repository without a parseable `origin`, and judged only the current branch. It printed
"SAFE" over a repository with no remote, unpushed commits on another branch, a stash, and
unpushed commits whose remote is not named `origin`.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup("sync")

from fleet_app import command_safe_to_wipe  # noqa: E402
from fleet_config import new_config  # noqa: E402

SECRET = "77" * 32
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(f"{label}\n{detail}")


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-qm", f"add {name}")


def pushed(tmp: Path, where: Path, remote_name: str = "origin") -> Path:
    """A clone at `where` whose every commit is on its (local, bare) remote."""
    bare = tmp / "remotes" / f"{where.name}-{abs(hash(str(where)))}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    git(tmp, "init", "-q", "--bare", str(bare))
    where.parent.mkdir(parents=True, exist_ok=True)
    git(tmp, "clone", "-q", "-o", remote_name, str(bare), str(where))
    commit(where, "base.txt")
    git(where, "push", "-q", "-u", remote_name, "main")
    return bare


def local_only(where: Path) -> Path:
    where.mkdir(parents=True)
    git(where, "init", "-q")
    commit(where, "only-copy.txt")
    return where


def verdict(roots: list[Path]) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = command_safe_to_wipe(new_config("machine-a", "A", roots, SECRET))
    return code, out.getvalue()


def side_branch(tmp, lib):
    repo = lib / "feature"
    pushed(tmp, repo)
    git(repo, "switch", "-qc", "wip")
    commit(repo, "wip.txt")
    git(repo, "switch", "-q", "main")


def stash(tmp, lib):
    repo = lib / "stashed"
    pushed(tmp, repo)
    (repo / "base.txt").write_text("edited", encoding="utf-8")
    git(repo, "stash", "-q")


def other_remote_name(tmp, lib):
    repo = lib / "renamed-remote"
    pushed(tmp, repo, remote_name="github")
    commit(repo, "unpushed.txt")


def local_tag(tmp, lib):
    repo = lib / "tagged"
    pushed(tmp, repo)
    git(repo, "switch", "-q", "--detach")
    commit(repo, "release.txt")
    git(repo, "tag", "v-local")
    git(repo, "switch", "-q", "main")


def detached_unique(tmp, lib):
    repo = lib / "detached"
    pushed(tmp, repo)
    git(repo, "switch", "-q", "--detach")
    commit(repo, "detached.txt")


def merge_in_progress(tmp, lib):
    repo = lib / "merging"
    pushed(tmp, repo)
    head = git(repo, "rev-parse", "HEAD").strip()
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").strip())
    (git_dir / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")


def untracked(tmp, lib):
    repo = lib / "untracked"
    pushed(tmp, repo)
    (repo / "notes.txt").write_text("never added", encoding="utf-8")


def unfetchable(tmp, lib):
    repo = lib / "gone-remote"
    bare = pushed(tmp, repo)
    git(repo, "remote", "set-url", "origin", str(bare.parent / "no-such-remote.git"))


def nested(tmp, lib):
    outer = lib / "outer"
    pushed(tmp, outer)
    (outer / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    git(outer, "add", ".gitignore")
    git(outer, "commit", "-qm", "ignore vendor")
    git(outer, "push", "-q")
    local_only(outer / "vendor" / "inner")


def bare_repo(tmp, lib):
    git(tmp, "init", "-q", "--bare", str(lib / "backup.git"))


AT_RISK = {
    "a repository with no remote": lambda tmp, lib: local_only(lib / "only-copy"),
    "unpushed commits on a branch that is not checked out": side_branch,
    "a stash": stash,
    "unpushed commits whose remote is not named origin": other_remote_name,
    "a tag on a commit no remote has": local_tag,
    "a commit only on a detached HEAD": detached_unique,
    "a merge in progress": merge_in_progress,
    "an untracked file": untracked,
    "a remote that cannot be fetched": unfetchable,
    "a hidden repository with no remote": lambda tmp, lib: local_only(lib / ".dotfiles"),
    "a no-remote repository under a folder discovery usually skips":
        lambda tmp, lib: local_only(lib / "Library" / "notes"),
    "a no-remote repository nested inside a clean one": nested,
    "a bare repository": bare_repo,
}

with tempfile.TemporaryDirectory(prefix="wipe-") as temp:
    base = Path(temp)

    def library(label: str) -> tuple[Path, Path]:
        tmp = base / label.replace(" ", "-")
        lib = tmp / "lib"
        pushed(tmp, lib / "clean")
        return tmp, lib

    tmp, lib = library("baseline")
    code, out = verdict([lib])
    check("a library where everything is pushed is SAFE", code == 0, out)
    check("SAFE names what it did not check", code == 0 and "ignored" in out.lower(), out)

    for label, build in AT_RISK.items():
        tmp, lib = library(label)
        build(tmp, lib)
        code, out = verdict([lib])
        check(f"NOT SAFE: {label}", code != 0 and "NOT SAFE" in out
              and "  clean:" not in out, out)  # the at-risk repository, not its clean neighbour

    # Behind is not at risk: everything this machine holds is on the remote.
    tmp, lib = library("behind")
    other = tmp / "elsewhere"
    git(tmp, "clone", "-q", str(next((tmp / "remotes").iterdir())), str(other))
    commit(other, "newer.txt")
    git(other, "push", "-q")
    code, out = verdict([lib])
    check("a clean repository that is only behind is SAFE", code == 0, out)

    # A detached HEAD on a pushed commit (a submodule's usual state) holds nothing unique.
    tmp, lib = library("detached-pushed")
    git(lib / "clean", "switch", "-q", "--detach")
    code, out = verdict([lib])
    check("a detached HEAD on a pushed commit is SAFE", code == 0, out)

    # A configured root that is itself a repository is checked too.
    tmp, lib = library("root-is-repo")
    root_repo = local_only(tmp / "solo")
    code, out = verdict([root_repo])
    check("NOT SAFE: a root that is itself an unpushed repository", code != 0, out)

    code, out = verdict([base / "does-not-exist"])
    check("a configured root that is missing is not SAFE", code != 0, out)

    empty = base / "empty"
    empty.mkdir()
    code, out = verdict([empty])
    check("no repositories at all is unproven, never SAFE", code != 0, out)

    # Read-only: the audit fetches, and changes no branch, file, stash or index.
    tmp, lib = library("read-only")
    stash(tmp, lib)
    before = git(lib / "stashed", "stash", "list") + git(lib / "stashed", "status", "--porcelain")
    verdict([lib])
    after = git(lib / "stashed", "stash", "list") + git(lib / "stashed", "status", "--porcelain")
    check("the audit changes nothing it inspects", before == after)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    for failure in FAILS:
        print("\n---", failure)
    raise SystemExit(1)
print("\nALL-SAFE-TO-WIPE-TESTS-PASS")
