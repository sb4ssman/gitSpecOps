"""Archive planning: the drift buckets and the publish classification, on synthetic data.

Formerly the self-test of `git-archive-updater/archive_diff.py`, which ran only when someone
invoked that module by hand. Names are invented on purpose: fixtures never carry a real
account, org or repository (the original once did; see `tests/repo/test_repo_hygiene.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._archive_plan import (  # noqa: E402
    LocalRepo,
    PublishCandidate,
    RepoRef,
    build_plan,
    build_publish_plan,
)


def _self_test() -> int:
    remote = [
        RepoRef(id="R_agent", owner="new-team", name="Agent-New-Team",
                url="https://github.com/new-team/Agent-New-Team"),
        RepoRef(id="R_wed", owner="new-team", name="event-site",
                url="https://github.com/new-team/event-site"),
        RepoRef(id="R_fam", owner="new-team", name="Shared-Clock",
                url="https://github.com/new-team/Shared-Clock"),
        RepoRef(id="R_new", owner="new-team", name="Brand-New-Repo",
                url="https://github.com/new-team/Brand-New-Repo"),
    ]
    local = [
        # org-only rename: folder matches new name, origin owner is stale; id supplied by caller
        LocalRepo(folder="Shared-Clock", origin="https://github.com/old-team/Shared-Clock",
                  owner_name="old-team/shared-clock", remote_id="R_fam"),
        # org + repo rename: folder and origin both stale; id supplied
        LocalRepo(folder="event-site.example", origin="https://github.com/old-team/event-site.example",
                  owner_name="old-team/event-site.example", remote_id="R_wed"),
        # triple drift: folder Agent-Old-Team, origin legacy-AGENT, upstream Agent-New-Team; id supplied
        LocalRepo(folder="Agent-Old-Team", origin="https://github.com/old-team/legacy-AGENT",
                  owner_name="old-team/legacy-agent", remote_id="R_agent", dirty=True),
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
    check("Shared-Clock origin_stale, folder OK",
          [(i.origin_stale, i.folder_mismatch) for i in plan.to_reconcile if i.local.folder == "Shared-Clock"],
          [(True, False)])
    check("event-site.example origin_stale + folder drift",
          [(i.origin_stale, i.folder_mismatch) for i in plan.to_reconcile if i.local.folder == "event-site.example"],
          [(True, True)])
    check("Agent dirty -> skipped, not pulled",
          [l.folder for l in plan.skipped_dirty], ["Agent-Old-Team"])
    check("pull excludes dirty Agent",
          sorted(l.folder for l in plan.to_pull), ["Shared-Clock", "event-site.example"])
    check("namespace rename detected",
          plan.namespace_renames, [("old-team", "new-team")])

    # Non-authoritative remote (no provider, or a failed/timed-out listing): we must fall back
    # to update-only and pull every clean repo, never mislabel them as orphans/local-only.
    loose = build_plan(local, [], remote_authoritative=False)
    check("non-authoritative pulls all clean repos",
          sorted(l.folder for l in loose.to_pull),
          ["Old-Experiment", "Shared-Clock", "event-site.example"])
    check("non-authoritative skips dirty", [l.folder for l in loose.skipped_dirty], ["Agent-Old-Team"])
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
    code = _self_test()
    if code == 0:
        print("ALL-ARCHIVE-PLAN-TESTS-PASS")
    raise SystemExit(code)
