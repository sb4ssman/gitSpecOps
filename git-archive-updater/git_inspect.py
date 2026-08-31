"""
git_inspect
===========

Read-only facts about *local* Git repositories. Host-agnostic: this module knows
nothing about GitHub, GitLab, or any remote API. It only runs `git` and parses URLs.

One task: given a folder, tell the caller what its child repositories are, what their
origins/branches are, and whether they are clean enough to fast-forward.

Generic primitives (run_git, URL parsing, child-dir listing) live in `shared/` and are
re-exported here so the archive modules' imports keep working.

Standalone:

    python git_inspect.py T:\\Github\\moon-and-back
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Shared special-operation primitives live in shared/ at the repo root. Make them
# importable whether this file runs as a script, a sibling import, or a package module.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.git_facts import (  # noqa: E402
    GIT_TIMEOUT_SECONDS,
    is_repo_root,
    git_stdout,
    git_top_level,
    run_git,
    set_git_timeout,
)
from shared.remote_identity import parse_remote_url, remote_host  # noqa: E402
from shared.repo_discovery import is_hidden, list_child_dirs  # noqa: E402


@dataclass
class RepoInfo:
    name: str            # local folder name
    path: str
    hidden: bool
    has_git_marker: bool
    is_work_tree: bool
    origin_present: bool
    origin: str | None
    host: str | None     # parsed from origin, e.g. "github.com" (for provider selection)
    approved_remote: bool
    branch: str | None
    dirty_work_tree: bool
    dirty_index: bool
    eligible: bool
    action: str
    result: str = "not run"
    elapsed_seconds: float = 0.0


# run_git / git_stdout / git_top_level / is_repo_root moved to shared/git_facts.py;
# is_hidden / list_child_dirs moved to shared/repo_discovery.py — all imported above.


# parse_remote_url / remote_host moved to shared/remote_identity.py (imported above).


def approved_remote(origin: str | None, prefixes: list[str]) -> bool:
    return bool(origin and any(origin.startswith(prefix) for prefix in prefixes))


def inspect_candidate(path: Path, approved_prefixes: list[str]) -> RepoInfo:
    started = time.perf_counter()
    has_git_marker = (path / ".git").exists()
    is_work_tree = is_repo_root(path)
    origin = git_stdout(path, ["remote", "get-url", "origin"]) if is_work_tree else None
    origin_ok = approved_remote(origin, approved_prefixes)
    branch = git_stdout(path, ["branch", "--show-current"]) if is_work_tree else None

    dirty_work_tree = False
    dirty_index = False
    if is_work_tree:
        dirty_work_tree = run_git(path, ["diff", "--quiet", "--ignore-submodules"]).returncode != 0
        dirty_index = run_git(path, ["diff", "--cached", "--quiet", "--ignore-submodules"]).returncode != 0

    if not has_git_marker and not is_work_tree:
        action = "skip: not a git repository"
    elif not is_work_tree:
        action = "skip: .git marker exists but folder is not a work tree"
    elif not origin:
        action = "skip: no origin remote"
    elif not origin_ok:
        action = "skip: origin is not approved"
    elif dirty_work_tree:
        action = "skip: working tree has local changes"
    elif dirty_index:
        action = "skip: index has staged changes"
    else:
        action = "eligible: pull --ff-only"

    return RepoInfo(
        name=path.name,
        path=str(path),
        hidden=is_hidden(path),
        has_git_marker=has_git_marker,
        is_work_tree=is_work_tree,
        origin_present=origin is not None,
        origin=origin,
        host=remote_host(origin),
        approved_remote=origin_ok,
        branch=branch,
        dirty_work_tree=dirty_work_tree,
        dirty_index=dirty_index,
        eligible=action.startswith("eligible:"),
        action=action,
        elapsed_seconds=round(time.perf_counter() - started, 3),
    )


def local_repo_origins(child_dirs: list[Path], approved_prefixes: list[str]) -> list[tuple[str, str]]:
    """Return (folder_name, origin_url) for each child that is a work tree with an approved origin."""
    found: list[tuple[str, str]] = []
    for path in child_dirs:
        info = inspect_candidate(path, approved_prefixes)
        if info.is_work_tree and info.origin and approved_remote(info.origin, approved_prefixes):
            found.append((info.name, info.origin))
    return found


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    print(f"Inspecting {root.resolve()}")
    for path in list_child_dirs(root):
        info = inspect_candidate(path, ["https://", "git@", "ssh://"])
        if info.is_work_tree:
            print(f"  {info.name}: branch={info.branch} host={info.host} "
                  f"dirty={'yes' if info.dirty_work_tree or info.dirty_index else 'no'} origin={info.origin}")
        else:
            print(f"  {info.name}: not a work tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
