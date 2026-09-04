"""
archive_diff
============

Pure logic. No git, no network, no filesystem. Given a set of *local* repos and a set of
*remote* repos, decide which bucket each falls into. This is the decision matrix, isolated
so it can be unit-tested with plain data and trusted ("we don't assume, ever").

Identity is by stable remote id first, then by normalized owner/name. Folder names and
origin URL strings are treated as drift signals, never as identity.

Standalone (runs the built-in self-test):

    python archive_diff.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# Canonical URL identity now lives in shared/ at the repo root; re-exported below so the
# archive modules' existing imports keep working.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.remote_identity import RepoRef, normalize_owner_name  # noqa: E402,F401


# RepoRef moved to shared/remote_identity.py (imported and re-exported above).


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


# normalize_owner_name moved to shared/remote_identity.py (imported and re-exported above).


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


# --------------------------------------------------------------------------------------
# Self-test: the real drift cases from the moon-and-back org (formerly solid-five-seven).
# --------------------------------------------------------------------------------------
def _self_test() -> int:
    remote = [
        RepoRef(id="R_agent", owner="moon-and-back", name="Agent-Moon-Back",
                url="https://github.com/moon-and-back/Agent-Moon-Back"),
        RepoRef(id="R_wed", owner="moon-and-back", name="ggm-wedding-site",
                url="https://github.com/moon-and-back/ggm-wedding-site"),
        RepoRef(id="R_fam", owner="moon-and-back", name="Family-Clock",
                url="https://github.com/moon-and-back/Family-Clock"),
        RepoRef(id="R_new", owner="moon-and-back", name="Brand-New-Repo",
                url="https://github.com/moon-and-back/Brand-New-Repo"),
    ]
    local = [
        # org-only rename: folder matches new name, origin owner is stale; id supplied by caller
        LocalRepo(folder="Family-Clock", origin="https://github.com/solid-five-seven/Family-Clock",
                  owner_name="solid-five-seven/family-clock", remote_id="R_fam"),
        # org + repo rename: folder and origin both stale; id supplied
        LocalRepo(folder="ggm-wedding.com", origin="https://github.com/solid-five-seven/ggm-wedding.com",
                  owner_name="solid-five-seven/ggm-wedding.com", remote_id="R_wed"),
        # triple drift: folder Agent-Five-Seven, origin hwh-AGENT, upstream Agent-Moon-Back; id supplied
        LocalRepo(folder="Agent-Five-Seven", origin="https://github.com/solid-five-seven/hwh-AGENT",
                  owner_name="solid-five-seven/hwh-agent", remote_id="R_agent", dirty=True),
        # a genuine local-only orphan, not in the org at all
        LocalRepo(folder="Old-Experiment", origin="https://github.com/someone-else/Old-Experiment",
                  owner_name="someone-else/old-experiment", remote_id=None),
    ]

    plan = build_plan(local, remote)
    failures: list[str] = []

    def check(label: str, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    check("clone == Brand-New-Repo", [r.name for r in plan.to_clone], ["Brand-New-Repo"])
    check("local_only == Old-Experiment", [l.folder for l in plan.local_only], ["Old-Experiment"])
    check("reconcile count", len(plan.to_reconcile), 3)
    check("Family-Clock origin_stale, folder OK",
          [(i.origin_stale, i.folder_mismatch) for i in plan.to_reconcile if i.local.folder == "Family-Clock"],
          [(True, False)])
    check("ggm-wedding.com origin_stale + folder drift",
          [(i.origin_stale, i.folder_mismatch) for i in plan.to_reconcile if i.local.folder == "ggm-wedding.com"],
          [(True, True)])
    check("Agent dirty -> skipped, not pulled",
          [l.folder for l in plan.skipped_dirty], ["Agent-Five-Seven"])
    check("pull excludes dirty Agent",
          sorted(l.folder for l in plan.to_pull), ["Family-Clock", "ggm-wedding.com"])
    check("namespace rename detected",
          plan.namespace_renames, [("solid-five-seven", "moon-and-back")])

    # Non-authoritative remote (no provider, or a failed/timed-out listing): we must fall back
    # to update-only and pull every clean repo, never mislabel them as orphans/local-only.
    loose = build_plan(local, [], remote_authoritative=False)
    check("non-authoritative pulls all clean repos",
          sorted(l.folder for l in loose.to_pull),
          ["Family-Clock", "Old-Experiment", "ggm-wedding.com"])
    check("non-authoritative skips dirty", [l.folder for l in loose.skipped_dirty], ["Agent-Five-Seven"])
    check("non-authoritative invents no clones/orphans",
          (len(loose.to_clone), len(loose.local_only), len(loose.to_reconcile)), (0, 0, 0))

    if failures:
        print("SELF-TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("archive_diff self-test passed: all drift buckets correct.")
    # --- push direction ---------------------------------------------------------------
    candidates = [
        PublishCandidate("clean-ahead", "main", "origin/main", ahead=2, behind=0),
        PublishCandidate("dirty-ahead", "main", "origin/main", ahead=1, behind=0, dirty=True),
        PublishCandidate("in-sync", "main", "origin/main", ahead=0, behind=0),
        PublishCandidate("behind-only", "main", "origin/main", ahead=0, behind=3),
        PublishCandidate("diverged", "main", "origin/main", ahead=1, behind=1),
        PublishCandidate("diverged-dirty", "main", "origin/main", ahead=1, behind=1, dirty=True),
        PublishCandidate("detached", None, None, ahead=None, behind=None),
        PublishCandidate("no-tracking", "main", None, ahead=None, behind=None),
    ]
    publish = build_publish_plan(candidates)
    expected = {"push": 1, "dirty_ahead": 1, "in_sync": 1, "behind": 1, "diverged": 2,
                "no_upstream": 2}
    if publish.counts() != expected:
        print(f"  FAIL publish counts: {publish.counts()} != {expected}")
        return 1
    if [c.folder for c in publish.to_push] != ["clean-ahead"]:
        print(f"  FAIL only ahead-only clean repos may be pushed: {publish.to_push}")
        return 1
    with_dirty = build_publish_plan(candidates, include_dirty=True)
    if sorted(c.folder for c in with_dirty.to_push) != ["clean-ahead", "dirty-ahead"]:
        print(f"  FAIL --include-dirty did not admit the dirty ahead repo: {with_dirty.to_push}")
        return 1
    if any(c.folder.startswith("diverged") for c in with_dirty.to_push):
        print("  FAIL a diverged repo became pushable")
        return 1
    print(f"  publish counts: {publish.counts()}")

    print(f"  plan counts: {plan.counts()}")
    print(f"  namespace renames: {plan.namespace_renames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
