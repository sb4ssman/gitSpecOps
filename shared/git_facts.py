"""
git_facts
=========

SHARED SPECIAL OPERATION: run `git` with consistent timeout/decoding behavior and report
repository facts. The fact functions and standalone CLI are read-only. The low-level
`run_git` process boundary is policy-neutral; archive apply code may reuse it only after
that tool's own preview/confirmation rules approve a mutation.

Shared rule: a method lives in `shared/` once two of the three special operations
(archive updater, org duplicator, sync suggester) need it. Stdlib only; no imports from
tool folders; no policy (approval lists and eligibility decisions stay per-tool).

Standalone:

    python shared/git_facts.py <repo-path>        # JSON facts for one repository
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    from shared.remote_identity import remote_host
except ImportError:  # run directly as a script from shared/: sibling import
    from remote_identity import remote_host

DEFAULT_GIT_TIMEOUT_SECONDS = 45
GIT_TIMEOUT_SECONDS = DEFAULT_GIT_TIMEOUT_SECONDS


def set_git_timeout(seconds: int) -> None:
    global GIT_TIMEOUT_SECONDS
    GIT_TIMEOUT_SECONDS = seconds


def run_git(repo_path: Path, args: Iterable[str], timeout: int | None = None,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run git in repo_path with a timeout. Never raises for ordinary git failures.

    Shared fact readers pass read-only commands. Archive apply code also reuses the process
    boundary for explicitly approved mutations, so callers—not this wrapper—own command policy.
    """
    timeout = GIT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, **(env or {})},
        )
    except (PermissionError, FileNotFoundError):
        return subprocess.CompletedProcess(list(args), returncode=1, stdout="", stderr="")
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            list(args),
            returncode=124,
            stdout=exc.stdout or "",
            stderr=f"timed out after {timeout}s",
        )


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


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    path = Path(argv[0])
    if not path.is_dir():
        print(f"Not a directory: {path}", file=sys.stderr)
        return 2
    print(json.dumps(repo_facts(path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
