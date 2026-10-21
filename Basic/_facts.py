"""Read-only facts about one repository: top level, branch, upstream, ahead/behind, dirtiness.

Nothing here changes a repository. Ambiguity is reported, never guessed: a detached HEAD has no
branch, a branch with no upstream has no counts, and both say so as ``None`` rather than a
plausible-looking default. `Basic/status.py` is the command over these facts.

`ref_snapshot` is the exception to "None on failure": it is taken to prove something later
(that a rewrite changed nothing it should not have), so it raises rather than come back empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from Basic._identity import remote_host
from Basic._objects import files_at, git_output
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


def shares_history(repo_path: Path) -> bool | None:
    """Whether HEAD and its upstream have any commit in common; None when git cannot say.

    False is not ordinary divergence: it means the upstream was rewritten (or replaced) after
    this clone was made, so every commit differs. `git pull` then refuses ("unrelated
    histories"), and forcing it would merge the old history back in.
    """
    proc = run_git(repo_path, ["merge-base", "HEAD", "@{upstream}"])
    if proc.returncode == 0:
        return True
    return False if proc.returncode == 1 else None


def remote_urls(repo_path: Path) -> dict[str, str]:
    """Every remote's fetch URL, by name. Empty when there is no remote (or git failed)."""
    proc = run_git(repo_path, ["remote", "-v"])
    urls: dict[str, str] = {}
    if proc.returncode != 0:
        return urls
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)":
            urls.setdefault(parts[0], parts[1])
    return urls


def root_commit(repo_path: Path) -> str | None:
    """The root commit reachable from HEAD, or None (no commits yet, or git failed).

    Identical in every clone of the same history, so it identifies a repository that has no
    remote. With several roots (merged histories) the smallest SHA is taken: any fixed rule
    works, as long as every machine applies the same one.
    """
    proc = run_git(repo_path, ["rev-list", "--max-parents=0", "HEAD"])
    roots = proc.stdout.split() if proc.returncode == 0 else []
    return min(roots) if roots else None


def unpushed_commits(repo_path: Path) -> int | None:
    """Commits reachable from HEAD, a local branch or a tag that no remote-tracking ref has.

    Unlike ahead/behind this covers every branch, not only the checked-out one, and needs no
    upstream. Counted against the remote-tracking refs as last fetched. None when git cannot say.
    """
    has_head = run_git(repo_path, ["rev-parse", "--verify", "-q", "HEAD"]).returncode == 0
    proc = run_git(repo_path, ["rev-list", "--count", *(["HEAD"] if has_head else []),
                               "--branches", "--tags", "--not", "--remotes"])
    text = proc.stdout.strip()
    return int(text) if proc.returncode == 0 and text.isdigit() else None


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


@dataclass(frozen=True)
class RefState:
    """One ref at one moment, with enough recorded to prove later what changed."""
    target: str                 # the ref's own value: a tag object, for an annotated tag
    commit: str
    tree: str
    commits: int                # commits reachable from it
    files: dict = field(default_factory=dict)   # path -> file version id at its tip


def ref_snapshot(repo_path: Path, prefixes: Iterable[str] = ("refs/heads", "refs/tags"), *,
                 with_files: bool = True) -> dict[str, RefState]:
    """Every ref under `prefixes` that names a commit. Raises `CommandFailed` on failure.

    Symbolic refs (`refs/remotes/origin/HEAD`) are left out: they are another ref's value. A tag
    naming a tree or a file version, not a commit, is left out too.
    """
    listing = git_output(repo_path, ["for-each-ref",
                                     "--format=%(refname)%00%(objectname)%00%(symref)",
                                     *prefixes])
    snapshot = {}
    for line in listing.splitlines():
        ref, target, symref = (line.split("\0") + ["", ""])[:3]
        if not ref or symref:
            continue
        commit = git_stdout(repo_path, ["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"])
        if not commit:
            continue
        snapshot[ref] = RefState(
            target=target, commit=commit,
            tree=git_output(repo_path, ["rev-parse", f"{commit}^{{tree}}"]).strip(),
            commits=int(git_output(repo_path, ["rev-list", "--count", commit]).strip()),
            files=files_at(repo_path, commit) if with_files else {},
        )
    return snapshot


def remote_refs(repo_path: Path, remote: str = "origin",
                timeout: float = 60) -> dict[str, str] | None:
    """`{ref: id}` as the remote holds them right now (`git ls-remote`), or None if unreachable.

    Network, read-only. What a remote *currently* serves -- the remote-tracking refs say only
    what it held at the last fetch.
    """
    proc = run_git(repo_path, ["ls-remote", "--refs", remote], timeout=timeout)
    if proc.returncode != 0:
        return None
    refs = {}
    for line in proc.stdout.splitlines():
        object_id, _, ref = line.partition("\t")
        if ref:
            refs[ref] = object_id
    return refs


def would_track(repo_path: Path, path: Path) -> bool:
    """Whether git could ever track a file at `path` in this repository.

    False only on positive evidence: outside the work tree, inside `.git`, or ignored. When git
    cannot answer, True -- a caller deciding where private data may live must assume the worst.
    """
    top = git_top_level(Path(repo_path))
    if top is None:
        return True
    try:
        relative = Path(path).resolve().relative_to(top)
    except ValueError:
        return False
    if relative.parts[:1] == (".git",):
        return False
    proc = run_git(top, ["check-ignore", "-q", "--no-index", "--", relative.as_posix()])
    return proc.returncode != 0


@dataclass(frozen=True)
class Setting:
    """A configuration value and where it came from."""
    value: str
    scope: str      # system, global, local, worktree, command
    origin: str     # the file (or other source) that set it


def identity_settings(repo_path: Path) -> dict[str, Setting | None]:
    """`user.name` and `user.email` as configured for this repository, each with its source.

    None for a key set nowhere -- git may then invent one from the account and host names;
    `next_commit_identity` shows what it would actually write.
    """
    settings: dict[str, Setting | None] = {}
    for key in ("user.name", "user.email"):
        proc = run_git(repo_path, ["config", "--show-scope", "--show-origin", "--get", key])
        scope, origin, value = (proc.stdout.rstrip("\n").split("\t", 2) + ["", "", ""])[:3]
        settings[key] = Setting(value, scope, origin) if proc.returncode == 0 else None
    return settings


def next_commit_identity(repo_path: Path) -> dict[str, tuple[str, str] | None]:
    """`{"author": (name, email), "committer": (name, email)}` that a commit made here now would
    carry -- configuration, environment variables and git's own guesses included. None for a
    role git cannot determine (it would refuse to commit)."""
    identities: dict[str, tuple[str, str] | None] = {}
    for role, variable in (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT")):
        ident = git_stdout(repo_path, ["var", variable]) or ""
        opening, closing = ident.rfind(" <"), ident.rfind(">")
        identities[role] = ((ident[:opening], ident[opening + 2:closing])
                            if 0 <= opening < closing else None)
    return identities
