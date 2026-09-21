"""Read-only observation of explicitly configured repository roots."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from Basic._discovery import find_repos  # noqa: E402
from Basic._facts import git_stdout, repo_facts  # noqa: E402
from Basic._identity import parse_remote_url  # noqa: E402
from Basic._run import run_git  # noqa: E402

from manifest import branch_id, repository_id, utc_now  # noqa: E402

DEFAULT_FETCH_WORKERS = 4
DEFAULT_FETCH_TIMEOUT_SECONDS = 60

# A background fetch must never stop to ask for credentials: nobody is there to answer. Git's
# terminal prompt and Git Credential Manager's sign-in window would both wait for a click that
# never comes, holding a worker until the timeout.
NON_INTERACTIVE_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
                           "GIT_OPTIONAL_LOCKS": "0"}

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
    # Local-only branch_id -> readable name. Branch names are published as digests, so this
    # is what lets a table show "main" instead of an opaque id — the same arrangement that
    # already keeps repository names off the wire.
    branches: dict[str, str] = field(default_factory=dict)


def _status_counts(repo_path: Path) -> tuple[int, int, int] | None:
    """Staged, unstaged and untracked entry counts from porcelain v2, or None if unreadable.

    None is never read as clean. A damaged index, a lock, or a timeout used to return zeros, so
    the one repository whose state could not be seen was reported as having nothing to commit.
    """
    result = run_git(
        repo_path,
        ["status", "--porcelain=v2", "-z", "--untracked-files=normal"],
        env={"GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        return None
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
    moves remote-tracking refs. It never prompts (see NON_INTERACTIVE_GIT_ENV): a repository
    whose credentials have expired fails in a second instead of blocking until the timeout.
    """
    result = run_git(repo_path, ["-c", "credential.interactive=never", "fetch", "--quiet",
                                 "--no-write-fetch-head"],
                     timeout=timeout, env=NON_INTERACTIVE_GIT_ENV)
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    return detail[-1][:160] if detail else f"git fetch exited {result.returncode}"


def fetch_repositories(paths: list[Path], workers: int = DEFAULT_FETCH_WORKERS,
                       timeout: int = DEFAULT_FETCH_TIMEOUT_SECONDS,
                       fetcher=None) -> tuple[dict[Path, str], list[str]]:
    """Fetch each repository. Returns `(fetched_at for each success, issues for each failure)`.

    House rule: failures are collected, never fatal. One repository that cannot be fetched must
    not cost the others their fetch. `fetcher` is the network boundary, injectable for tests.
    """
    fetcher = fetcher or _fetch
    fetched_at: dict[Path, str] = {}
    issues: list[str] = []
    if not paths:
        return fetched_at, issues

    def guarded(path: Path) -> str | None:
        try:
            return fetcher(path, timeout)
        except Exception as exc:  # noqa: BLE001 - one repository never stops the rest
            return f"{type(exc).__name__}: {exc}"

    # Network-bound, so a small pool is a large win; bounded so a big archive cannot open
    # hundreds of connections at once.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for path, error in zip(paths, pool.map(guarded, paths)):
            if error is None:
                fetched_at[path] = utc_now()
            else:
                issues.append(f"fetch failed, using cached refs: {path.name}: {error}")
    return fetched_at, issues


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
    """
    issues: list[str] = []
    paths = _discover(roots, issues)
    fetched_at: dict[Path, str] = {}
    if fetch and paths:
        fetched_at, fetch_issues = fetch_repositories(paths, fetch_workers, fetch_timeout, fetcher)
        issues.extend(fetch_issues)
    observed = observe_paths(paths, secret, fetched_at=fetched_at, progress=progress)
    observed.issues = issues + observed.issues
    return observed


def observe_paths(paths: list[Path], secret: str | None = None,
                  fetched_at: dict[Path, str] | None = None, progress=None) -> Observation:
    """Inspect known repository roots without rediscovering their parent libraries.

    This is the event-driven observer's targeted path: a filesystem event identifies the
    affected checkout, then only that checkout pays for Git status commands. It performs no
    network activity and never mutates the repository.

    A repository whose facts cannot be read is left out *with an issue*, never reported with
    guessed counts. A caller holding a last-known record keeps it (see IncrementalObserver).
    """
    repositories: list[dict] = []
    catalog: dict[str, dict] = {}
    branches: dict[str, str] = {}
    issues: list[str] = []
    fetched_at = {Path(key).resolve(): value for key, value in (fetched_at or {}).items()}
    normalized = [Path(path).expanduser().resolve() for path in paths]

    for index, path in enumerate(normalized, start=1):
        if progress is not None:
            progress(index, len(normalized), path)
        if not path.is_dir():
            issues.append(f"repository disappeared: {path}")
            continue
        facts = repo_facts(path)
        if not facts.get("is_work_tree"):
            # Commonly Git refusing a folder owned by another account ("dubious ownership").
            issues.append(f"git cannot read this repository (check folder ownership or "
                          f"safe.directory): {path}")
            continue
        parsed = parse_remote_url(facts.get("origin"))
        if not parsed:
            issues.append(f"missing or unrecognized origin: {path}")
            continue
        counts = _status_counts(path)
        if counts is None:
            issues.append(f"status unreadable, so uncommitted work cannot be ruled out: {path}")
            continue
        host, owner, name = parsed
        repo_id = repository_id(host, owner, name, secret)
        staged, unstaged, untracked = counts
        stash_text = git_stdout(path, ["rev-list", "--walk-reflogs", "--count", "refs/stash"])
        repositories.append({
            "repo_id": repo_id,
            "branch_id": branch_id(facts.get("branch"), secret),
            "has_upstream": bool(facts.get("upstream")),
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
        local_branch = facts.get("branch")
        if local_branch:
            branches[branch_id(local_branch, secret)] = local_branch

    repositories.sort(key=lambda repo: catalog[repo["repo_id"]]["display_name"].lower())
    return Observation(repositories=repositories, catalog=catalog, issues=issues,
                       branches=branches)
