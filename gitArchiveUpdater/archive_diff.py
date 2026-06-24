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

from dataclasses import dataclass, field


@dataclass
class RepoRef:
    """A remote repository, as reported by a provider. `id` is a provider-stable identity
    that survives repo and namespace (owner/org/group) renames."""
    id: str
    owner: str
    name: str
    url: str
    host: str = "github.com"
    private: bool = False
    fork: bool = False
    archived: bool = False


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


def normalize_owner_name(url: str | None) -> str | None:
    """Lowercased 'owner/name' from any common git URL, host-agnostic. None if unparseable."""
    if not url:
        return None
    text = url.strip()
    if text.startswith("git@"):
        _, _, path = text[len("git@"):].partition(":")
    elif "://" in text:
        _, _, rest = text.partition("://")
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        _, _, path = rest.partition("/")
    else:
        return None
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2:
        return None
    return f"{segments[0]}/{segments[-1]}".lower()


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
    print(f"  plan counts: {plan.counts()}")
    print(f"  namespace renames: {plan.namespace_renames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
