"""Read-only facts about one repository: top level, branch, upstream, ahead/behind, dirtiness.

Nothing here changes a repository. Ambiguity is reported, never guessed: a detached HEAD has no
branch, a branch with no upstream has no counts, and both say so as ``None`` rather than a
plausible-looking default. `Basic/status.py` is the command over these facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from Basic._identity import remote_host
from Basic._run import run_git


def git_stdout(repo_path: Path, args: Iterable[str]) -> str | None:
    """Stripped stdout of a git command, or None on failure/empty."""
    proc = run_git(repo_path, args)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def git_top_level(path: Path) -> Path | None:
    """The work tree root containing path, or None if not inside a work tree."""
    top_level = git_stdout(path, ["rev-parse", "--show-toplevel"])
    if not top_level:
        return None
    return Path(top_level).resolve()


def is_repo_root(path: Path) -> bool:
    """True when path is itself a git work tree root."""
    return git_top_level(path) == path.resolve()


def ahead_behind(repo_path: Path) -> dict | None:
    """Commits ahead of / behind the upstream of the current branch, or None.

    {"behind": N, "ahead": M} — behind = commits only on the upstream,
    ahead = commits only on HEAD. None when there is no upstream (or git failed).
    """
    proc = run_git(repo_path, ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"])
    if proc.returncode != 0:
        return None
    parts = proc.stdout.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return {"behind": int(parts[0]), "ahead": int(parts[1])}


def repo_facts(repo_path: Path) -> dict:
    """Read-only facts about one repository. Ambiguity is reported, never guessed."""
    path = Path(repo_path)
    is_work_tree = is_repo_root(path)
    branch = git_stdout(path, ["branch", "--show-current"]) if is_work_tree else None
    upstream = (
        git_stdout(path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        if is_work_tree else None
    )
    counts = ahead_behind(path) if (is_work_tree and upstream) else None
    origin = git_stdout(path, ["remote", "get-url", "origin"]) if is_work_tree else None
    dirty_work_tree = bool(
        is_work_tree and run_git(path, ["diff", "--quiet", "--ignore-submodules"]).returncode
    )
    dirty_index = bool(
        is_work_tree and run_git(path, ["diff", "--cached", "--quiet", "--ignore-submodules"]).returncode
    )
    return {
        "name": path.name,
        "path": str(path),
        "has_git_marker": (path / ".git").exists(),
        "is_work_tree": is_work_tree,
        "branch": branch,           # None on a detached HEAD too — ambiguity preserved
        "upstream": upstream,
        "ahead": counts["ahead"] if counts else None,
        "behind": counts["behind"] if counts else None,
        "origin": origin,
        "host": remote_host(origin),
        "dirty_work_tree": dirty_work_tree,
        "dirty_index": dirty_index,
    }
