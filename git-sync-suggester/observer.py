"""Read-only observation of explicitly configured repository roots."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.git_facts import git_stdout, repo_facts, run_git  # noqa: E402
from shared.remote_identity import parse_remote_url  # noqa: E402
from shared.repo_discovery import find_repos  # noqa: E402

from manifest import repository_id, utc_now  # noqa: E402

DEFAULT_FETCH_WORKERS = 4
DEFAULT_FETCH_TIMEOUT_SECONDS = 60

# An in-progress operation is a "stop and finish this" signal, and it is the difference
# between a dirty tree someone chose and a repository left mid-surgery. Each marker is a
# path inside the git dir; the first match wins.
_OPERATION_MARKERS = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
)


@dataclass(frozen=True)
class RootSpec:
    path: Path
    recursive: bool = False


@dataclass
class Observation:
    repositories: list[dict]
    catalog: dict[str, dict]
    issues: list[str]


def _status_counts(repo_path: Path) -> tuple[int, int, int]:
    """Return staged, unstaged, and untracked entry counts from porcelain v2."""
    result = run_git(
        repo_path,
        ["status", "--porcelain=v2", "-z", "--untracked-files=normal"],
        env={"GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        return 0, 0, 0
    records = result.stdout.split("\0")
    staged = unstaged = untracked = 0
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith("? "):
            untracked += 1
            continue
        if record[0] not in "12u" or len(record.split()) < 2:
            continue
        xy = record.split()[1]
        staged += int(xy[0] != ".")
        unstaged += int(xy[1] != ".")
        if record.startswith("2 "):
            index += 1  # porcelain -z emits the original rename path as another field
    return staged, unstaged, untracked


def _in_progress_operation(repo_path: Path) -> str | None:
    """Name the operation this repository is in the middle of, if any."""
    git_dir = git_stdout(repo_path, ["rev-parse", "--absolute-git-dir"])
    if not git_dir:
        return None
    base = Path(git_dir)
    for marker, name in _OPERATION_MARKERS:
        if (base / marker).exists():
            return name
    return None


def _fetch(repo_path: Path, timeout: int) -> str | None:
    """Update remote-tracking refs. Returns an error message, or None on success.

    Never touches the working tree or any local branch — `git fetch` with no refspec only
    moves remote-tracking refs. `GIT_TERMINAL_PROMPT=0` is the lesson the org duplicator
    already paid for: without it a repository whose credentials have expired blocks on an
    invisible prompt until the timeout instead of failing in under a second.
    """
    result = run_git(repo_path, ["fetch", "--quiet"], timeout=timeout,
                     env={"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    return detail[-1][:160] if detail else f"git fetch exited {result.returncode}"


def _discover(roots: list[RootSpec], issues: list[str]) -> list[Path]:
    """Every work-tree repository inside the configured roots, de-duplicated."""
    found: list[Path] = []
    seen: set[Path] = set()
    for spec in roots:
        root = spec.path.expanduser()
        try:
            hits = find_repos(root, max_depth=None if spec.recursive else 0)
        except NotADirectoryError:
            issues.append(f"not a directory: {root}")
            continue
        for hit in hits:
            path = Path(hit.path).resolve()
            if path in seen:
                continue
            seen.add(path)
            if hit.kind == "bare":
                issues.append(f"bare repository has no working-tree state: {path}")
                continue
            found.append(path)
    return found


def observe_roots(roots: list[RootSpec], secret: str | None = None, fetch: bool = False,
                  fetch_workers: int = DEFAULT_FETCH_WORKERS,
                  fetch_timeout: int = DEFAULT_FETCH_TIMEOUT_SECONDS,
                  progress=None, fetcher=None) -> Observation:
    """Read every configured root. `secret` salts repository identities for publication;
    omit it only for a local preview that is never published.

    `fetch` opts in to network activity: remote-tracking refs are refreshed before facts are
    read, so ahead/behind become current rather than cached, and `upstream_observed_at` is
    stamped for the repositories that actually succeeded. Without it, ahead/behind remain
    honest-but-cached and `upstream_observed_at` stays null.

    `fetcher` is the network boundary, injectable so tests can exercise success and failure
    without a network — the same discipline that makes `watcher.py` testable.
    """
    fetcher = fetcher or _fetch
    repositories: list[dict] = []
    catalog: dict[str, dict] = {}
    issues: list[str] = []

    paths = _discover(roots, issues)
    fetched_at: dict[Path, str] = {}
    if fetch and paths:
        # Network-bound, so a small pool is a large win; bounded so a big archive cannot
        # open hundreds of connections at once.
        def guarded(path: Path) -> str | None:
            # House rule: failures are collected, never fatal. One repository that cannot be
            # fetched must not cost the observation of every other repository.
            try:
                return fetcher(path, fetch_timeout)
            except Exception as exc:
                return f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(max_workers=max(1, fetch_workers)) as pool:
            for path, error in zip(paths, pool.map(guarded, paths)):
                if error is None:
                    fetched_at[path] = utc_now()
                else:
                    issues.append(f"fetch failed, using cached refs: {path.name}: {error}")

    for index, path in enumerate(paths, start=1):
        if progress is not None:
            progress(index, len(paths), path)
        facts = repo_facts(path)
        parsed = parse_remote_url(facts.get("origin"))
        if not parsed:
            issues.append(f"missing or unrecognized origin: {path}")
            continue
        host, owner, name = parsed
        repo_id = repository_id(host, owner, name, secret)
        staged, unstaged, untracked = _status_counts(path)
        stash_text = git_stdout(path, ["rev-list", "--walk-reflogs", "--count", "refs/stash"])
        repositories.append({
            "repo_id": repo_id,
            "branch": facts.get("branch"),
            "upstream": facts.get("upstream"),
            "upstream_observed_at": fetched_at.get(path),
            "ahead": facts.get("ahead"),
            "behind": facts.get("behind"),
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "stashes": int(stash_text) if stash_text and stash_text.isdigit() else 0,
            "operation": _in_progress_operation(path),
        })
        # Local-only: the catalog is never published, so it may hold the full identity.
        # host/owner are what let `converge` ask a provider to name a peer's hash.
        catalog[repo_id] = {"display_name": name, "path": str(path),
                            "host": host, "owner": owner, "name": name}

    repositories.sort(key=lambda repo: catalog[repo["repo_id"]]["display_name"].lower())
    return Observation(repositories=repositories, catalog=catalog, issues=issues)
