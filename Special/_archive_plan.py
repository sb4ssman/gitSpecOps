"""Archive planning: which repositories in an archive qualify for what, decided from facts.

Everything here is judgment over data -- the part that makes an archive update *special* rather
than a loop of pulls. No network, and the only git it runs is read-only fact gathering
(`inspect_candidate`). Two directions, kept apart on purpose:

- **Pull direction.** `inspect_candidate` decides fast-forward eligibility for one folder
  (work tree, approved origin, clean). `build_plan` buckets a whole archive against the
  authoritative remote set: pull / clone / reconcile / skip-dirty / local-only. Identity is by
  stable remote id first, then normalized owner/name; folder names and origin strings are
  drift signals, never identity.
- **Push direction.** `build_publish_plan` admits only ahead-only repositories. It does not
  reuse the pull guarantees: a push needs write auth, can trigger CI, and is refused by git
  when it is not a fast-forward -- which is the one property this relies on.

`tests/special/test_archive_plan.py` pins the drift buckets and the publish classification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from Basic._discovery import is_hidden
from Basic._facts import git_stdout, is_repo_root
from Basic._identity import RepoRef, normalize_owner_name, remote_host
from Basic._run import run_git

DEFAULT_APPROVED_REMOTE_PREFIXES = ["https://github.com/", "git@github.com:", "ssh://git@github.com/"]

__all__ = ["DEFAULT_APPROVED_REMOTE_PREFIXES", "LocalRepo", "PublishCandidate", "PublishPlan",
           "ReconcileItem", "RepoInfo", "RepoRef", "SyncPlan", "approved_remote",
           "build_plan", "build_publish_plan", "inspect_candidate", "normalize_owner_name"]


# --------------------------------------------------------------------------------------
# One folder: is it a repository we may fast-forward?
# --------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------
# A whole archive against its remote: the drift buckets.
# --------------------------------------------------------------------------------------
@dataclass
class LocalRepo:
    """A local clone. `remote_id` is filled by the caller (via a provider) only when a cheap
    name match fails, so that a renamed-upstream repo can still be matched by id."""
    folder: str            # local folder name (may be a deliberate user choice)
    origin: str            # origin URL as configured locally (may be stale after a rename)
    owner_name: str | None # normalized "owner/name" parsed from origin, lowercased
    dirty: bool = False
    remote_id: str | None = None


@dataclass
class ReconcileItem:
    """A matched repo whose local representation has drifted from the current upstream."""
    local: LocalRepo
    ref: RepoRef
    origin_stale: bool      # origin URL no longer points at the canonical upstream
    folder_mismatch: bool   # local folder name differs from current upstream name


@dataclass
class SyncPlan:
    to_pull: list[LocalRepo] = field(default_factory=list)        # clean, matched -> ff pull
    skipped_dirty: list[LocalRepo] = field(default_factory=list)  # matched but dirty -> never touch
    to_clone: list[RepoRef] = field(default_factory=list)         # in org, no local clone
    to_reconcile: list[ReconcileItem] = field(default_factory=list)  # origin/folder drift
    local_only: list[LocalRepo] = field(default_factory=list)     # on disk, not in org -> review only
    namespace_renames: list[tuple[str, str]] = field(default_factory=list)  # (old_owner, new_owner)

    def counts(self) -> dict[str, int]:
        return {
            "pull": len(self.to_pull),
            "clone": len(self.to_clone),
            "reconcile": len(self.to_reconcile),
            "skipped_dirty": len(self.skipped_dirty),
            "local_only": len(self.local_only),
        }


def build_plan(
    local_repos: list[LocalRepo],
    remote_repos: list[RepoRef],
    remote_authoritative: bool = True,
) -> SyncPlan:
    """Categorize every local and remote repo. Pure: matching only, no side effects.

    Matching order per local repo:
      1. by normalized owner/name against remote URLs (cheap, exact) -> origin is current
      2. by remote_id (filled by caller via provider redirect) -> origin is stale (renamed upstream)
      3. otherwise -> local-only (orphan; never assumed deleted)
    Any remote repo left unmatched is missing locally and a clone candidate.

    `remote_authoritative` says whether `remote_repos` is the *true, complete* remote set.
    When it is False (no provider for the host, or the listing failed/timed out) we know
    nothing about what exists remotely, so we must NOT label local repos as orphans or
    missing. We degrade to host-agnostic update-only: every clean work tree is a pull
    candidate, every dirty one is skipped, and there are no clone/reconcile/local-only
    buckets. This matches the standalone archive_updater behavior and the documented
    "loose archive -> update-only" promise. An empty-but-authoritative listing (a genuinely
    empty org) is different: there every local repo really is local-only.
    """
    plan = SyncPlan()

    if not remote_authoritative:
        for local in local_repos:
            if local.dirty:
                plan.skipped_dirty.append(local)
            else:
                plan.to_pull.append(local)
        return plan


    remote_by_owner_name = {f"{r.owner}/{r.name}".lower(): r for r in remote_repos}
    remote_by_id = {r.id: r for r in remote_repos}
    matched_ids: set[str] = set()
    stale_owners: dict[str, str] = {}  # old_owner -> new_owner, for namespace-rename messaging

    for local in local_repos:
        ref = remote_by_owner_name.get(local.owner_name) if local.owner_name else None
        origin_stale = False
        if ref is None and local.remote_id is not None:
            ref = remote_by_id.get(local.remote_id)
            origin_stale = ref is not None

        if ref is None:
            plan.local_only.append(local)
            continue

        matched_ids.add(ref.id)

        if origin_stale and local.owner_name:
            old_owner = local.owner_name.split("/", 1)[0]
            if old_owner != ref.owner.lower():
                stale_owners[old_owner] = ref.owner

        folder_mismatch = local.folder.lower() != ref.name.lower()
        if origin_stale or folder_mismatch:
            plan.to_reconcile.append(
                ReconcileItem(local=local, ref=ref, origin_stale=origin_stale, folder_mismatch=folder_mismatch)
            )

        if local.dirty:
            plan.skipped_dirty.append(local)
        else:
            plan.to_pull.append(local)

    plan.to_clone = [r for r in remote_repos if r.id not in matched_ids]
    plan.namespace_renames = sorted(stale_owners.items())
    return plan


# --------------------------------------------------------------------------------------
# The push direction ("publish"). Pure classification only — no git, no network.
#
# Pull is safe because a fast-forward can never destroy data or require a choice. Push is
# not: it needs write auth, it can trigger CI and other agents, and a careless force can
# overwrite history. So this does NOT reuse the pull guarantees. The one provably safe
# primitive is a push WITHOUT --force, which git itself refuses when it is not a
# fast-forward — the mirror image of `pull --ff-only`.
#
# Everything here is a judgement about *eligibility*. Nothing is pushed by this module.
# --------------------------------------------------------------------------------------

@dataclass
class PublishCandidate:
    """One local repo's push-direction facts, as read by the caller."""
    folder: str
    branch: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    dirty: bool = False

    @property
    def has_direction(self) -> bool:
        """False when there is no upstream to compare against (or a detached HEAD)."""
        return bool(self.branch and self.upstream
                    and self.ahead is not None and self.behind is not None)


@dataclass
class PublishPlan:
    to_push: list = field(default_factory=list)       # ahead-only, clean -> non-force push
    dirty_ahead: list = field(default_factory=list)   # ahead but uncommitted work present
    in_sync: list = field(default_factory=list)       # nothing to do
    behind: list = field(default_factory=list)        # pull first; nothing to publish
    diverged: list = field(default_factory=list)      # ahead AND behind -> human decision
    no_upstream: list = field(default_factory=list)   # detached / no tracking -> direction unknown

    def counts(self) -> dict[str, int]:
        return {
            "push": len(self.to_push),
            "dirty_ahead": len(self.dirty_ahead),
            "in_sync": len(self.in_sync),
            "behind": len(self.behind),
            "diverged": len(self.diverged),
            "no_upstream": len(self.no_upstream),
        }


def build_publish_plan(candidates: list[PublishCandidate],
                       include_dirty: bool = False) -> PublishPlan:
    """Classify repos by push direction. Only ahead-only repos are ever eligible.

    `include_dirty` moves ahead-but-dirty repos into `to_push`. Pushing from a dirty tree is
    technically safe — a push moves commits, not the working tree — but it is excluded by
    default because publishing work from a repository someone is still mid-edit in is
    surprising, and surprise is the thing to avoid in the first slice of a write feature.
    A dirty tree is NEVER auto-committed under any flag.
    """
    plan = PublishPlan()
    for candidate in candidates:
        if not candidate.has_direction:
            plan.no_upstream.append(candidate)
            continue
        ahead, behind = candidate.ahead, candidate.behind
        if ahead and behind:
            plan.diverged.append(candidate)
        elif ahead:
            if candidate.dirty and not include_dirty:
                plan.dirty_ahead.append(candidate)
            else:
                plan.to_push.append(candidate)
        elif behind:
            plan.behind.append(candidate)
        else:
            plan.in_sync.append(candidate)
    return plan
