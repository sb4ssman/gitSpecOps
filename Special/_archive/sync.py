"""
archive_sync
============

The plan/apply engine for an archive of sibling repos. Bulk-first, graceful, never assumes.

Five phases:
  1. DETECT   - scan local repos + (if a provider matches the host) the authoritative remote
                set; reconcile identity by stable id so renames (repo AND namespace) survive.
  2. PLAN     - categorize everything into buckets (pull / clone / reconcile / dirty / local-only).
  3. DECIDE   - the caller approves whole classes (bulk). Nothing ambiguous is auto-applied.
  4. EXECUTE  - run approved classes; every operation is wrapped so a failure is collected and
                skipped, never fatal. Bulk keeps moving.
  5. REVIEW   - return issues to the common runner for masked presentation.

Modes (CLI):
  (default)         scan + report only, no changes
  --update          + fast-forward pull existing repos
  --sync            + clone repos missing locally (update implied)
  --reconcile       + rewrite stale origin URLs to the canonical upstream
  --rename-folders  + rename local folders to match the upstream name (guarded)
  --yes             approve explicit actions outside a terminal; otherwise review a masked plan

Updating existing repos is host-agnostic and works with no provider. Discovery/clone/reconcile
require a provider for the repos' host; where none exists the archive degrades to update-only.
Allowed remote prefixes constrain local action targets and upstream clone URLs; out-of-scope
candidates are reported as issues. Empty prefix strings are invalid, not an allow-all shortcut.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._discovery import list_child_dirs  # noqa: E402
from Basic._facts import is_repo_root, repo_facts  # noqa: E402
from Basic._providers._registry import provider_for  # noqa: E402
from Basic._run import CommandFailed, run_git  # noqa: E402
from Basic.clone import clone  # noqa: E402
from Basic.pull import fast_forward  # noqa: E402
from Special.security._push import PushResult, PushSnapshot, publish_checked, read_push_snapshot  # noqa: E402
from Special._archive.plan import (  # noqa: E402
    DEFAULT_APPROVED_REMOTE_PREFIXES,
    LocalRepo,
    PublishCandidate,
    RepoRef,
    SyncPlan,
    build_plan,
    build_publish_plan,
    approved_remote,
    inspect_candidate,
    normalize_owner_name,
)

#: --publish pushes (never forced). The scheduled and generated paths never pass it.
EFFECT = "remote"
APP_NAME = "Archive Sync"
VERSION = "0.1.0"


@dataclass
class Issue:
    repo: str
    action: str
    detail: str


@dataclass
class DetectResult:
    root: str
    plan: SyncPlan
    owner: str | None = None
    provider_name: str | None = None
    remote_count: int | None = None
    errors: list[Issue] = field(default_factory=list)
    # True only when we obtained the complete remote repo set. False when there is no provider
    # for the host, or the provider's listing failed/timed out -> we degrade to update-only.
    remote_authoritative: bool = True


# --------------------------------------------------------------------------------------
# Phase 1: DETECT
# --------------------------------------------------------------------------------------
def detect_plan(root: Path, approved_prefixes: list[str], owner_override: str | None = None) -> DetectResult:
    if any(not isinstance(prefix, str) or not prefix.strip() for prefix in approved_prefixes):
        raise ValueError("allowed remote prefixes must be nonempty strings")
    errors: list[Issue] = []
    child_dirs = list_child_dirs(root)
    infos = [inspect_candidate(p, approved_prefixes) for p in child_dirs]
    blocked = [i for i in infos if i.is_work_tree and i.origin and not i.approved_remote]
    errors.extend(Issue(repo=i.name, action="scope", detail="origin is outside allowed remote prefixes")
                  for i in blocked)
    work_trees = [i for i in infos if i.is_work_tree and i.origin and i.approved_remote]

    # Pick a provider from the first repo whose host has one.
    provider = None
    sample_origin = None
    for info in work_trees:
        p = provider_for(info.origin)
        if p is not None:
            provider, sample_origin = p, info.origin
            break

    locals_ = [
        LocalRepo(
            folder=i.name,
            origin=i.origin,
            owner_name=normalize_owner_name(i.origin),
            dirty=i.dirty_work_tree or i.dirty_index,
        )
        for i in work_trees
    ]

    # No provider -> host-agnostic: update-only plan (everything clean is a pull candidate).
    if provider is None:
        return DetectResult(
            root=str(root), plan=build_plan(locals_, [], remote_authoritative=False),
            owner=None, provider_name=None, errors=errors, remote_authoritative=False,
        )

    # Resolve the canonical owner. Listing a renamed OLD owner 404s, so resolve via a repo
    # redirect: ask the provider for one known repo and read its current owner.
    owner = owner_override
    if owner is None:
        spec = normalize_owner_name(sample_origin)
        ref, err = provider.resolve(spec) if spec else (None, "could not parse a repo to resolve owner")
        if ref is None:
            errors.append(Issue(repo=spec or "?", action="resolve-owner", detail=err or "unknown"))
            # Fall back to the stale owner string; list_repos may still work if not renamed.
            owner = spec.split("/", 1)[0] if spec else None
        else:
            owner = ref.owner

    remote: list[RepoRef] = []
    listing_ok = False
    if owner:
        listed, err = provider.list_repos(owner)
        if err or listed is None:
            errors.append(Issue(repo=owner, action="list-repos", detail=err or "no repos returned"))
            remote = []
        else:
            remote = [ref for ref in listed if approved_remote(ref.url, approved_prefixes)]
            errors.extend(Issue(repo=ref.name, action="scope", detail="upstream URL is outside allowed remote prefixes")
                          for ref in listed if not approved_remote(ref.url, approved_prefixes))
            listing_ok = True

    # Could not get an authoritative remote set (no owner resolved, or the listing failed). We
    # know nothing about what exists remotely, so degrade to update-only rather than dumping
    # every local repo into "local-only / missing". Fast-forward pulls stay safe and useful.
    if not listing_ok:
        return DetectResult(
            root=str(root), plan=build_plan(locals_, [], remote_authoritative=False),
            owner=owner, provider_name=getattr(provider, "name", "?"),
            remote_count=None, errors=errors, remote_authoritative=False,
        )

    # First pass by name/URL; then resolve ids only for the leftovers (renamed-upstream repos).
    plan = build_plan(locals_, remote)
    if plan.local_only and remote:
        by_id = {r.id: r for r in remote}
        changed = False
        for local in plan.local_only:
            if provider_for(local.origin) is None:
                continue  # different host; leave as a genuine orphan
            ref, err = provider.resolve(local.owner_name) if local.owner_name else (None, "no owner/name")
            if ref is not None and ref.id in by_id:
                local.remote_id = ref.id
                changed = True
            elif err and "not found" not in err.lower():
                errors.append(Issue(repo=local.folder, action="resolve", detail=err))
        if changed:
            plan = build_plan(locals_, remote)

    return DetectResult(
        root=str(root), plan=plan, owner=owner,
        provider_name=getattr(provider, "name", "?"), remote_count=len(remote), errors=errors,
    )


# --------------------------------------------------------------------------------------
# Phase 2: PLAN / ALERT
# --------------------------------------------------------------------------------------
def apply_pull(root: Path, plan: SyncPlan, issues: list[Issue], *, emit=None) -> int:
    """Apply selected pulls; optional callback avoids process-global stdout capture."""
    done = 0
    for local in plan.to_pull:
        path = root / local.folder
        result = fast_forward(path)
        if result.startswith("failed:"):
            result = "failed: pull did not complete; inspect Git locally"
        if emit is not None:
            emit(f"  [PULL] {local.folder}: {result}")
        if result.startswith("failed:"):
            issues.append(Issue(repo=local.folder, action="pull", detail=result.removeprefix("failed: ")))
        else:
            done += 1
    return done


def apply_clone(root: Path, plan: SyncPlan, issues: list[Issue], *, emit=None) -> int:
    """Apply selected clones; optional callback avoids process-global stdout capture."""
    emit = emit or (lambda *_: None)
    done = 0
    for ref in plan.to_clone:
        dest = root / ref.name
        emit(f"  [CLONE] {ref.owner}/{ref.name}")
        if dest.exists():
            emit("skip: folder exists")
            issues.append(Issue(repo=ref.name, action="clone", detail="destination folder already exists"))
            continue
        proc = clone(ref.url, dest)
        if proc.returncode != 0:
            detail = "clone did not complete; inspect Git locally"
            emit(f"failed: {detail}")
            issues.append(Issue(repo=ref.name, action="clone", detail=detail))
        else:
            emit("cloned")
            done += 1
    return done


def apply_reconcile_origins(root: Path, plan: SyncPlan, issues: list[Issue], *, emit=None) -> int:
    """Rewrite only selected stale origins; finite diagnostics, no implicit terminal output."""
    emit = emit or (lambda *_: None)
    done = 0
    for it in plan.to_reconcile:
        if not it.origin_stale:
            continue
        path = root / it.local.folder
        emit(f"  [ORIGIN] {it.local.folder}")
        proc = run_git(path, ["remote", "set-url", "origin", it.ref.url])
        if proc.returncode != 0:
            emit("failed: origin update did not complete")
            issues.append(Issue(repo=it.local.folder, action="origin", detail="origin update did not complete; inspect Git locally"))
        else:
            emit("fixed")
            done += 1
    return done


def apply_rename_folders(root: Path, plan: SyncPlan, issues: list[Issue], *, emit=None) -> int:
    """Rename only selected clean folders into absent targets; no deletion or overwrite."""
    emit = emit or (lambda *_: None)
    done = 0
    for it in plan.to_reconcile:
        if not it.folder_mismatch:
            continue
        src, dest = root / it.local.folder, root / it.ref.name
        emit(f"  [RENAME] {it.local.folder} -> {it.ref.name}")
        if it.local.dirty:
            emit("skip: dirty work tree")
            issues.append(Issue(repo=it.local.folder, action="rename", detail="uncommitted changes; left as-is"))
            continue
        if dest.exists():
            emit("skip: target exists")
            issues.append(Issue(repo=it.local.folder, action="rename", detail=f"target '{it.ref.name}' already exists"))
            continue
        try:
            src.rename(dest)
            emit("renamed")
            done += 1
        except OSError as exc:  # locked folder (Windows), permissions, etc.
            emit("skip: locked/in use")
            issues.append(Issue(repo=it.local.folder, action="rename", detail="folder could not be renamed; inspect locally"))
    return done


# --------------------------------------------------------------------------------------
# Phase 5: REVIEW
# --------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------
# Publish: the push direction. Its OWN apply class.
#
# This publication path is deliberately narrow: a policy-checked commit id goes to one
# selected branch, with ordinary fast-forward checks. It is never implied by --update or
# --sync, and the generated launchers and
# scheduled tasks never pass it — the same rule that keeps --reconcile and --rename-folders
# interactive-only.
# --------------------------------------------------------------------------------------

DEFAULT_PUBLISH_PAUSE_SECONDS = 1.0


def _publish_dirty(path: Path, facts: dict) -> bool:
    """Dirtiness for the publish decision, which is broader than the pull decision.

    `repo_facts` reports tracked changes only, which is right for fast-forward eligibility —
    untracked files never block a pull. For publishing, though, "is someone mid-edit here?"
    is the question, and an untracked file answers it just as well as a modified one. So this
    uses `git status --porcelain`, which sees untracked files too. Kept local to the publish
    path on purpose: making the shared fact stricter would needlessly narrow pull eligibility.
    """
    if facts.get("dirty_work_tree") or facts.get("dirty_index"):
        return True
    status = run_git(path, ["status", "--porcelain"], env={"GIT_OPTIONAL_LOCKS": "0"})
    if status.returncode != 0:
        return True  # cannot prove it is clean, so do not publish from it
    return bool(status.stdout.strip())


def collect_publish_candidates(root: Path) -> list[PublishCandidate]:
    """Read push-direction facts for every direct-child repo under root."""
    candidates = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if not is_repo_root(child):
            continue
        facts = repo_facts(child)
        try:
            snapshot = read_push_snapshot(child)
            if (snapshot.branch.removeprefix("refs/heads/") != facts.get("branch") or
                    snapshot.remote + "/" + snapshot.destination.removeprefix("refs/heads/") != facts.get("upstream")):
                snapshot = None
        except (CommandFailed, OSError, ValueError):
            snapshot = None
        candidates.append(PublishCandidate(
            folder=child.name,
            branch=facts.get("branch"),
            upstream=facts.get("upstream"),
            ahead=facts.get("ahead"),
            behind=facts.get("behind"),
            dirty=_publish_dirty(child, facts),
            push_snapshot=snapshot,
        ))
    return candidates


def _publish_one(path: Path, candidate: PublishCandidate, *, settings_home=None, expected_policy=None) -> PushResult:
    """Check and publish exactly the planned tip/target through the shared security operation."""
    snapshot = candidate.push_snapshot
    if not isinstance(snapshot, PushSnapshot) or snapshot.repo != path.absolute():
        return PushResult("incomplete", "Push target could not be bound; review branch/remote settings and rebuild the plan.")
    return publish_checked(snapshot, settings_home=settings_home, expected_policy=expected_policy)


def apply_publish(root: Path, plan, issues: list[Issue],
                  pause: float = DEFAULT_PUBLISH_PAUSE_SECONDS, *, settings_home=None,
                  emit=None, results=None, before_action=None, expected_policies=None) -> int:
    """Publish selected immutable snapshots; status controls success, never message wording."""
    done = 0
    for index, candidate in enumerate(plan.to_push):
        path = root / candidate.folder
        if before_action is not None:
            before_action()
        result = _publish_one(path, candidate, settings_home=settings_home,
                              expected_policy=(expected_policies or {}).get(candidate.folder))
        if results is not None:
            results.append({"folder": candidate.folder, **result.record()})
        if emit is not None:
            emit(f"  [PUSH] {candidate.folder}: {result.message}")
        if result.status not in ("pushed", "already-current"):
            issues.append(Issue(repo=candidate.folder, action="publish",
                                detail=result.message))
        else:
            done += 1
        # Deliberate pacing: a burst of pushes across an org can trigger a CI storm or a
        # rate limit. Slower is fine; this is never on a hot path.
        if pause and index < len(plan.to_push) - 1:
            time.sleep(pause)
    return done

def build_report(result: DetectResult, applied: dict[str, int], issues: list[Issue], mode: str) -> dict:
    plan = result.plan
    return {
        "tool": APP_NAME,
        "version": VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "root": result.root,
        "type": ("org" if result.remote_authoritative else "update-only") if result.provider_name else "loose",
        "remote_authoritative": result.remote_authoritative,
        "provider": result.provider_name,
        "owner": result.owner,
        "remote_count": result.remote_count,
        "mode": mode,
        "namespace_renames": [list(pair) for pair in plan.namespace_renames],
        "plan": {
            "pull": [l.folder for l in plan.to_pull],
            "clone": [f"{r.owner}/{r.name}" for r in plan.to_clone],
            "reconcile": [
                {"folder": it.local.folder, "target": it.ref.name,
                 "origin_stale": it.origin_stale, "folder_mismatch": it.folder_mismatch}
                for it in plan.to_reconcile
            ],
            "skipped_dirty": [l.folder for l in plan.skipped_dirty],
            "local_only": [{"folder": l.folder, "origin": l.origin} for l in plan.local_only],
        },
        "applied": applied,
        "issues": [{"repo": i.repo, "action": i.action, "detail": i.detail} for i in issues],
    }

