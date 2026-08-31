"""Offline tests for duplicator local repository discovery.

All names are synthetic. The test creates only a disposable temporary directory and
does not invoke git, access the network, or modify a real repository.
"""

import sys
import tempfile
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent / "github-org-duplicator"
sys.path.insert(0, str(TOOL_DIR))

from local_repos import duplicate_repo_names, scan_local_git_repos  # noqa: E402


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

if failures:
    print("LOCAL-REPOS-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-LOCAL-REPOS-TESTS-PASS")
