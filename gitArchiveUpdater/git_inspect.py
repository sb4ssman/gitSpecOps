"""
git_inspect
===========

Read-only facts about *local* Git repositories. Host-agnostic: this module knows
nothing about GitHub, GitLab, or any remote API. It only runs `git` and parses URLs.

One task: given a folder, tell the caller what its child repositories are, what their
origins/branches are, and whether they are clean enough to fast-forward.

Standalone:

    python git_inspect.py T:\\Github\\moon-and-back
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_GIT_TIMEOUT_SECONDS = 45
GIT_TIMEOUT_SECONDS = DEFAULT_GIT_TIMEOUT_SECONDS


def set_git_timeout(seconds: int) -> None:
    global GIT_TIMEOUT_SECONDS
    GIT_TIMEOUT_SECONDS = seconds


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


def run_git(repo_path: Path, args: Iterable[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    timeout = GIT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
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
    proc = run_git(repo_path, args)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def git_top_level(path: Path) -> Path | None:
    top_level = git_stdout(path, ["rev-parse", "--show-toplevel"])
    if not top_level:
        return None
    return Path(top_level).resolve()


def is_repo_root(path: Path) -> bool:
    return git_top_level(path) == path.resolve()


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def list_child_dirs(root: Path) -> list[Path]:
    return sorted(
        [item for item in root.iterdir() if item.is_dir()],
        key=lambda item: item.name.lower(),
    )


def parse_remote_url(url: str | None) -> tuple[str, str, str] | None:
    """Parse any common git remote URL into (host, owner, name), host-agnostic.

    Handles:
        https://host/owner/.../name(.git)
        git@host:owner/.../name(.git)
        ssh://git@host/owner/.../name(.git)
    For nested namespaces (e.g. GitLab groups) the first path segment is the owner and
    the last is the name; the middle is ignored for identity purposes.
    Returns None when the URL is not a recognizable git remote.
    """
    if not url:
        return None
    text = url.strip()
    host = ""
    if text.startswith("git@"):
        # git@host:owner/name
        rest = text[len("git@"):]
        host, _, path = rest.partition(":")
    elif "://" in text:
        # scheme://[user@]host/owner/name
        _scheme, _, rest = text.partition("://")
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        host, _, path = rest.partition("/")
    else:
        return None
    if not host or not path:
        return None
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [seg for seg in path.split("/") if seg]
    if len(segments) < 2:
        return None
    owner, name = segments[0], segments[-1]
    return host.lower(), owner, name


def remote_host(url: str | None) -> str | None:
    parsed = parse_remote_url(url)
    return parsed[0] if parsed else None


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
