"""Offline tests for duplicator local repository discovery.

All names are synthetic. The test creates only a disposable temporary directory and
does not invoke git, access the network, or modify a real repository.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic._console import enable_unicode_output  # noqa: E402
from Special._org_duplicator.local_repos import (  # noqa: E402
    duplicate_repo_names,
    safe_cleanup_directory,
    scan_local_git_repos,
)

enable_unicode_output()  # as the duplicator's entry point does; cleanup prints ⚠


def make_worktree(path):
    (path / ".git").mkdir(parents=True)


def make_gitfile(path):
    path.mkdir(parents=True)
    (path / ".git").write_text("gitdir: ../synthetic-git-dir\n", encoding="utf-8")


def make_bare(path):
    (path / "objects").mkdir(parents=True)
    (path / "refs").mkdir()
    (path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


def names(repos):
    return [repo["name"] for repo in repos]


failures = []
with tempfile.TemporaryDirectory(prefix="repo-discovery-test-") as temp:
    root = Path(temp)
    make_worktree(root / "alpha-repo")
    make_bare(root / "beta-repo.git")
    make_worktree(root / "group" / "gamma-repo")
    make_gitfile(root / "group" / "delta-repo")

    direct = scan_local_git_repos(root, recursive=False)
    recursive = scan_local_git_repos(root, recursive=True)

    if names(direct) != ["alpha-repo", "beta-repo"]:
        failures.append(f"direct scan: {names(direct)}")
    if names(recursive) != ["alpha-repo", "beta-repo", "delta-repo", "gamma-repo"]:
        failures.append(f"recursive scan: {names(recursive)}")
    kinds = {repo["name"]: repo["repo_kind"] for repo in recursive}
    if kinds.get("beta-repo") != "bare" or kinds.get("delta-repo") != "gitfile":
        failures.append(f"repository kinds: {kinds}")

    collisions = duplicate_repo_names([
        {"name": "same-repo", "path": "/synthetic/a"},
        {"name": "SAME-REPO", "path": "/synthetic/b"},
        {"name": "other-repo", "path": "/synthetic/c"},
    ])
    if list(collisions) != ["same-repo"]:
        failures.append(f"duplicate names: {collisions}")

# --- cleanup deletes only what discovery itself calls a repository ---------------------------
# The bug this pins (2026-10-19): any folder holding an entry named `config` or `HEAD` was
# treated as a repository and deleted. The batch download skips only folders the scan above
# recognizes, so a plain project folder sharing a repository's name reached the cleanup -- and
# a `config/` subfolder, common in ordinary projects, was enough to have it removed.
with tempfile.TemporaryDirectory(prefix="cleanup-test-") as temp:
    parent = Path(temp) / "dest"

    lookalikes = {
        "config-folder": lambda p: (p / "config").mkdir(parents=True),
        "config-file": lambda p: (p.mkdir(parents=True), (p / "config").write_text("x")),
        "head-file": lambda p: (p.mkdir(parents=True), (p / "HEAD").write_text("x")),
    }
    for name, build in lookalikes.items():
        folder = parent / name
        build(folder)
        (folder / "precious.txt").write_text("exists nowhere else\n", encoding="utf-8")
        if scan_local_git_repos(parent / name):
            failures.append(f"{name}: the scan should not call this a repository")
        if safe_cleanup_directory(str(folder), str(parent), name):
            failures.append(f"{name}: cleanup reported success on a non-repository")
        if not (folder / "precious.txt").exists():
            failures.append(f"{name}: a non-repository folder was deleted")

    make_worktree(parent / "real-clone")
    if not safe_cleanup_directory(str(parent / "real-clone"), str(parent), "real-clone"):
        failures.append("a real repository inside the parent was not cleaned up")
    if (parent / "real-clone").exists():
        failures.append("cleanup reported success but the repository is still there")

    make_bare(parent / "mirror-clone.git")
    if not safe_cleanup_directory(str(parent / "mirror-clone.git"), str(parent), "mirror-clone"):
        failures.append("a real mirror repository inside the parent was not cleaned up")

    outside = Path(temp) / "elsewhere"
    make_worktree(outside)
    if safe_cleanup_directory(str(outside), str(parent), "elsewhere") or not outside.exists():
        failures.append("cleanup reached outside its parent")
    make_worktree(parent)
    if safe_cleanup_directory(str(parent), str(parent), "dest") or not parent.exists():
        failures.append("cleanup deleted the parent folder itself")

if failures:
    print("LOCAL-REPOS-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-LOCAL-REPOS-TESTS-PASS")
