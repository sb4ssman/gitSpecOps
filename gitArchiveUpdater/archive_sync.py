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
  5. REVIEW   - print everything that failed or needs a human, as one batch.

Modes (CLI):
  (default)         scan + report only, no changes
  --update          + fast-forward pull existing repos
  --sync            + clone repos missing locally (update implied)
  --reconcile       + rewrite stale origin URLs to the canonical upstream
  --rename-folders  + rename local folders to match the upstream name (guarded)
  --yes             apply without interactive confirmation (for cron); otherwise asks per class

Updating existing repos is host-agnostic and works with no provider. Discovery/clone/reconcile
require a provider for the repos' host; where none exists the archive degrades to update-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from .archive_diff import LocalRepo, RepoRef, SyncPlan, build_plan, normalize_owner_name
    from .git_inspect import (
        inspect_candidate,
        list_child_dirs,
        run_git,
        set_git_timeout,
    )
    from .remote_provider import provider_for
except ImportError:
    from archive_diff import LocalRepo, RepoRef, SyncPlan, build_plan, normalize_owner_name
    from git_inspect import inspect_candidate, list_child_dirs, run_git, set_git_timeout
    from remote_provider import provider_for

APP_NAME = "Archive Sync"
VERSION = "0.1.0"
DEFAULT_APPROVED_REMOTE_PREFIXES = ["https://github.com/", "git@github.com:", "ssh://git@github.com/"]
# Matches archive_manager's DEFAULT_REPORT_DIR so the dashboard's "latest report" picks these up.
DEFAULT_REPORT_DIR = ".gitSpecOps/archive-updates"


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
    errors: list[Issue] = []
    child_dirs = list_child_dirs(root)
    infos = [inspect_candidate(p, approved_prefixes) for p in child_dirs]
    work_trees = [i for i in infos if i.is_work_tree and i.origin]

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
            owner=None, provider_name=None, remote_authoritative=False,
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
            remote = listed
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
def render_plan(result: DetectResult) -> None:
    plan = result.plan
    print("=" * 64)
    print(f"Archive: {result.root}")
    if result.provider_name and result.remote_authoritative:
        print(f"Type: org archive  ({result.provider_name}: {result.owner}, {result.remote_count} remote repos)")
    elif result.provider_name:
        print(f"Type: update-only  ({result.provider_name} discovery unavailable for "
              f"{result.owner or '?'} -> updating local repos only; see issues below)")
    else:
        print("Type: loose archive  (no remote provider for these hosts -> update-only)")
    print("=" * 64)

    if plan.namespace_renames:
        for old, new in plan.namespace_renames:
            print(f"!! Namespace renamed upstream: {old} -> {new}  (origins are stale)")

    counts = plan.counts()
    print(f"  pull (fast-forward):      {counts['pull']}")
    print(f"  clone (missing locally):  {counts['clone']}")
    print(f"  reconcile (name/origin):  {counts['reconcile']}")
    print(f"  skip (dirty work tree):   {counts['skipped_dirty']}")
    print(f"  local-only (review):      {counts['local_only']}")

    if plan.to_clone:
        print("\n  Missing locally (clone candidates):")
        for r in plan.to_clone:
            print(f"    + {r.owner}/{r.name}{_flags(r)}")
    if plan.to_reconcile:
        print("\n  Drifted (reconcile candidates):")
        for it in plan.to_reconcile:
            bits = []
            if it.origin_stale:
                bits.append(f"origin -> {it.ref.url}")
            if it.folder_mismatch:
                bits.append(f"folder '{it.local.folder}' -> '{it.ref.name}'")
            print(f"    ~ {it.local.folder}: {'; '.join(bits)}")
    if plan.skipped_dirty:
        print("\n  Skipped (uncommitted local changes, never touched):")
        for l in plan.skipped_dirty:
            print(f"    ! {l.folder}")
    if plan.local_only:
        print("\n  Local-only (on disk, not in org -> your call, no action taken):")
        for l in plan.local_only:
            print(f"    ? {l.folder}  ({l.origin})")
    print()


def _flags(r: RepoRef) -> str:
    f = [n for n, v in (("private", r.private), ("fork", r.fork), ("archived", r.archived)) if v]
    return f" ({', '.join(f)})" if f else ""


# --------------------------------------------------------------------------------------
# Phase 4: EXECUTE (each step graceful; collects issues)
# --------------------------------------------------------------------------------------
def _fast_forward(path: Path) -> str:
    fetch = run_git(path, ["fetch", "origin"])
    if fetch.returncode != 0:
        return f"failed: fetch: {fetch.stderr.strip() or 'error'}"
    pull = run_git(path, ["pull", "--ff-only"])
    if pull.returncode != 0:
        return f"failed: pull --ff-only: {pull.stderr.strip() or 'not a fast-forward'}"
    combined = f"{pull.stdout}\n{pull.stderr}".lower()
    return "already current" if ("up to date" in combined or "up-to-date" in combined) else "updated"


def apply_pull(root: Path, plan: SyncPlan, issues: list[Issue]) -> int:
    done = 0
    for local in plan.to_pull:
        path = root / local.folder
        print(f"  [PULL] {local.folder} ... ", end="", flush=True)
        result = _fast_forward(path)
        print(result)
        if result.startswith("failed:"):
            issues.append(Issue(repo=local.folder, action="pull", detail=result.removeprefix("failed: ")))
        else:
            done += 1
    return done


def apply_clone(root: Path, plan: SyncPlan, issues: list[Issue]) -> int:
    done = 0
    for ref in plan.to_clone:
        dest = root / ref.name
        print(f"  [CLONE] {ref.owner}/{ref.name} ... ", end="", flush=True)
        if dest.exists():
            print("skip: folder exists")
            issues.append(Issue(repo=ref.name, action="clone", detail="destination folder already exists"))
            continue
        proc = run_git(root, ["clone", ref.url, str(dest)], timeout=300)
        if proc.returncode != 0:
            detail = (proc.stderr.strip() or "error").splitlines()[-1]
            print(f"failed: {detail}")
            issues.append(Issue(repo=ref.name, action="clone", detail=detail))
        else:
            print("cloned")
            done += 1
    return done


def apply_reconcile_origins(root: Path, plan: SyncPlan, issues: list[Issue]) -> int:
    done = 0
    for it in plan.to_reconcile:
        if not it.origin_stale:
            continue
        path = root / it.local.folder
        print(f"  [ORIGIN] {it.local.folder} -> {it.ref.url} ... ", end="", flush=True)
        proc = run_git(path, ["remote", "set-url", "origin", it.ref.url])
        if proc.returncode != 0:
            print(f"failed: {proc.stderr.strip() or 'error'}")
            issues.append(Issue(repo=it.local.folder, action="origin", detail=proc.stderr.strip() or "error"))
        else:
            print("fixed")
            done += 1
    return done


def apply_rename_folders(root: Path, plan: SyncPlan, issues: list[Issue]) -> int:
    done = 0
    for it in plan.to_reconcile:
        if not it.folder_mismatch:
            continue
        src, dest = root / it.local.folder, root / it.ref.name
        print(f"  [RENAME] {it.local.folder} -> {it.ref.name} ... ", end="", flush=True)
        if it.local.dirty:
            print("skip: dirty work tree")
            issues.append(Issue(repo=it.local.folder, action="rename", detail="uncommitted changes; left as-is"))
            continue
        if dest.exists():
            print("skip: target exists")
            issues.append(Issue(repo=it.local.folder, action="rename", detail=f"target '{it.ref.name}' already exists"))
            continue
        try:
            src.rename(dest)
            print("renamed")
            done += 1
        except OSError as exc:  # locked folder (Windows), permissions, etc.
            print("skip: locked/in use")
            issues.append(Issue(repo=it.local.folder, action="rename", detail=f"{exc.__class__.__name__}: {exc}"))
    return done


# --------------------------------------------------------------------------------------
# Phase 5: REVIEW
# --------------------------------------------------------------------------------------
def review(issues: list[Issue]) -> None:
    if not issues:
        print("No issues. Everything applied cleanly.")
        return
    print("=" * 64)
    print(f"Needs your attention: {len(issues)} item(s)")
    print("=" * 64)
    for i in issues:
        print(f"  [{i.action}] {i.repo}: {i.detail}")


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


def write_report(root: Path, payload: dict) -> Path:
    output_dir = root / DEFAULT_REPORT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = output_dir / f"archive-update-{stamp}.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return report_path


def _ask(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan/apply sync for an archive of sibling repos.")
    p.add_argument("--root", type=Path, action="append", help="Archive folder. Repeatable. Defaults to cwd.")
    p.add_argument("--github-owner", help="Override the detected owner/org (rarely needed).")
    p.add_argument("--approved-remote-prefix", action="append", help="Allowed origin prefix. Repeatable.")
    p.add_argument("--update", action="store_true", help="Fast-forward pull existing repos.")
    p.add_argument("--sync", action="store_true", help="Update + clone repos missing locally.")
    p.add_argument("--reconcile", action="store_true", help="Also rewrite stale origin URLs.")
    p.add_argument("--rename-folders", action="store_true", help="Also rename folders to match upstream (guarded).")
    p.add_argument("--yes", action="store_true", help="Apply without interactive confirmation (for cron).")
    p.add_argument("--no-report", action="store_true", help="Do not write a dated JSON report.")
    p.add_argument("--git-timeout", type=int, default=45, help="Per-git-command timeout seconds.")
    return p.parse_args()


def run_one(root: Path, approved_prefixes: list[str], args: argparse.Namespace) -> int:
    result = detect_plan(root, approved_prefixes, owner_override=args.github_owner)
    render_plan(result)
    issues = list(result.errors)
    applied = {"pulled": 0, "cloned": 0, "origins_fixed": 0, "renamed": 0}

    do_update = args.update or args.sync or args.reconcile or args.rename_folders
    if not do_update:
        print("Scan only: no changes made. Pass --update or --sync to apply.")
        mode = "scan-only"
    else:
        plan = result.plan
        print("Applying:")
        if plan.to_pull and _ask(f"Fast-forward {len(plan.to_pull)} repo(s)?", args.yes):
            applied["pulled"] = apply_pull(root, plan, issues)
        if args.sync and plan.to_clone and _ask(f"Clone {len(plan.to_clone)} missing repo(s)?", args.yes):
            applied["cloned"] = apply_clone(root, plan, issues)
        if args.reconcile:
            stale = [it for it in plan.to_reconcile if it.origin_stale]
            if stale and _ask(f"Rewrite {len(stale)} stale origin URL(s)?", args.yes):
                applied["origins_fixed"] = apply_reconcile_origins(root, plan, issues)
        if args.rename_folders:
            drift = [it for it in plan.to_reconcile if it.folder_mismatch]
            if drift and _ask(f"Rename {len(drift)} folder(s) to match upstream?", args.yes):
                applied["renamed"] = apply_rename_folders(root, plan, issues)
        mode = "sync" if args.sync else "update"
        print()

    review(issues)
    if not args.no_report:
        report_path = write_report(root, build_report(result, applied, issues, mode))
        print(f"Report: {report_path}")
    return 1 if issues else 0


def main() -> int:
    args = parse_args()
    set_git_timeout(args.git_timeout)
    approved = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES
    roots = args.root or [Path.cwd()]
    print(f"{APP_NAME} v{VERSION}")
    rc = 0
    for root in roots:
        resolved = root.resolve()
        if not resolved.is_dir():
            print(f"Not a directory: {resolved}", file=sys.stderr)
            rc = 2
            continue
        rc = run_one(resolved, approved, args) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
