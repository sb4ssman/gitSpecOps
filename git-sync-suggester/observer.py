"""Read-only observation of explicitly configured repository roots."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.git_facts import git_stdout, repo_facts, run_git  # noqa: E402
from shared.remote_identity import parse_remote_url  # noqa: E402
from shared.repo_discovery import find_repos  # noqa: E402

from manifest import repository_id  # noqa: E402


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


def observe_roots(roots: list[RootSpec], secret: str | None = None) -> Observation:
    """Read every configured root. `secret` salts repository identities for publication;
    omit it only for a local preview that is never published."""
    repositories: list[dict] = []
    catalog: dict[str, dict] = {}
    issues: list[str] = []
    seen_paths: set[Path] = set()

    for spec in roots:
        root = spec.path.expanduser()
        try:
            hits = find_repos(root, max_depth=None if spec.recursive else 0)
        except NotADirectoryError:
            issues.append(f"not a directory: {root}")
            continue
        for hit in hits:
            path = Path(hit.path).resolve()
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if hit.kind == "bare":
                issues.append(f"bare repository has no working-tree state: {path}")
                continue
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
                "upstream_observed_at": None,
                "ahead": facts.get("ahead"),
                "behind": facts.get("behind"),
                "staged": staged,
                "unstaged": unstaged,
                "untracked": untracked,
                "stashes": int(stash_text) if stash_text and stash_text.isdigit() else 0,
                "operation": None,
            })
            # Local-only: the catalog is never published, so it may hold the full identity.
            # host/owner are what let `converge` ask a provider to name a peer's hash.
            catalog[repo_id] = {"display_name": name, "path": str(path),
                                "host": host, "owner": owner, "name": name}

    repositories.sort(key=lambda repo: catalog[repo["repo_id"]]["display_name"].lower())
    return Observation(repositories=repositories, catalog=catalog, issues=issues)
