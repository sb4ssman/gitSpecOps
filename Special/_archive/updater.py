"""
Archive Updater
===============

Host-agnostic update of a folder of sibling Git repositories: scan direct child folders,
print an inventory, and (unless --scan-only) `git pull --ff-only` every clean repo whose
origin is approved. Works with ANY git remote and any platform — it needs only `git`.

This is the conservative, universal half of gitSpecOps. It never merges, rebases, resets,
force-pushes, installs dependencies, runs project code, clones, or renames. Discovery of
remote repos that aren't cloned locally, cloning them, and reconciling renames are the job
of archive_sync.py (which requires a remote provider such as the GitHub `gh` CLI).

Eligibility comes from `Special/_archive/plan.py`; the fast-forward is `Basic/pull.py`. This
file is scan + fast-forward + report.

Usage:
    python Special/update_archive.py                      # update the current folder
    python Special/update_archive.py --scan-only          # inventory only
    python Special/update_archive.py --root /path/to/archive
    python Special/update_archive.py --root A --root B     # several roots
    python Special/update_archive.py --output-dir REPORTS  # write a dated result in the selected format
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._discovery import is_hidden, list_child_dirs  # noqa: E402
from Basic.pull import fast_forward  # noqa: E402
from Special._runtime.files import checked_path, excluded, linked
from Special._archive.plan import (  # noqa: E402
    DEFAULT_APPROVED_REMOTE_PREFIXES,
    RepoInfo,
    inspect_candidate,
)

EFFECT = "local"
APP_NAME = "Archive Updater"
VERSION = "0.4.0"


@dataclass
class RootReport:
    root: str
    generated: str
    hidden_folders: list[str]
    regular_folders: list[str]
    candidate_folders: list[str]
    git_repositories: list[str]
    non_repo_folders: list[str]
    repos: list[RepoInfo]
    elapsed_seconds: float = 0.0
    excluded_folders: int = 0


def scan_root(root: Path, approved_prefixes: list[str], *, exclude_paths=()) -> RootReport:
    started = time.perf_counter()
    child_dirs, excluded_count = [], 0
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if linked(path) or excluded(path, exclude_paths, contains=True):
            excluded_count += 1
            continue
        if path.is_dir():
            child_dirs.append(path)
    repos = [inspect_candidate(path, approved_prefixes) for path in child_dirs]
    report = RootReport(
        root=str(root),
        generated=datetime.now().isoformat(timespec="seconds"),
        hidden_folders=[p.name for p in child_dirs if is_hidden(p)],
        regular_folders=[p.name for p in child_dirs if not is_hidden(p)],
        candidate_folders=[p.name for p in child_dirs],
        git_repositories=[r.name for r in repos if r.is_work_tree],
        non_repo_folders=[r.name for r in repos if not r.is_work_tree],
        repos=repos,
        excluded_folders=excluded_count,
    )
    report.elapsed_seconds = round(time.perf_counter() - started, 3)
    return report


def print_list(title: str, names: list[str], *, stream=None) -> None:
    emit = partial(print, file=stream)
    emit(f"{title}: {len(names)}")
    for name in names:
        emit(f"  - {name}")
    if not names:
        emit("  - none")


def print_scan(report: RootReport, show_remote_urls: bool, *, stream=None) -> None:
    emit = partial(print, file=stream)
    emit(f"Scan Root: {report.root}")
    emit(f"Generated: {report.generated}")
    emit(f"Scan time: {report.elapsed_seconds:.3f}s")
    emit()
    print_list("Git repositories", report.git_repositories, stream=stream)
    print_list("Non-repo folders", report.non_repo_folders, stream=stream)
    emit()
    emit("Candidate details:")
    for repo in report.repos:
        origin = repo.origin if (repo.origin and show_remote_urls) else ("present" if repo.origin_present else "none")
        emit(f"  {repo.name}: work_tree={'yes' if repo.is_work_tree else 'no'} "
              f"host={repo.host or '-'} branch={repo.branch or '-'} "
              f"dirty={'yes' if repo.dirty_work_tree or repo.dirty_index else 'no'} "
              f"origin={origin} action={repo.action}")
    emit()


def update_repo(repo: RepoInfo) -> str:
    return fast_forward(Path(repo.path))


def run_updates(report: RootReport, *, emit=print, log=None, before_action=None) -> None:
    emit = emit or (lambda *_: None)
    for repo in report.repos:
        if repo.eligible:
            if before_action is not None:
                before_action()
            emit(f"[PULL] {repo.name}")
            started = time.perf_counter()
            if log is not None:
                log.event("repository_started", attempted=1)
            repo.result = update_repo(repo)
            repo.elapsed_seconds = round(time.perf_counter() - started, 3)
            if log is not None:
                log.event("repository_finished", updated=int(repo.result == "updated"),
                          failed=int(repo.result.startswith("failed:")))
            emit(f"       {repo.result} ({repo.elapsed_seconds:.3f}s)")
        else:
            repo.result = repo.action
            emit(f"[SKIP] {repo.name} - {repo.action.removeprefix('skip: ')}")


def build_summary(report: RootReport) -> dict[str, list[str]]:
    dirty_actions = {"skip: working tree has local changes", "skip: index has staged changes"}
    remote_actions = {"skip: no origin remote", "skip: origin is not approved"}
    skipped_non_repo = [r.name for r in report.repos if r.result == "skip: not a git repository"]
    skipped_dirty = [r.name for r in report.repos if r.result in dirty_actions]
    skipped_remote = [r.name for r in report.repos if r.result in remote_actions]
    known = set(skipped_non_repo + skipped_dirty + skipped_remote)
    return {
        "updated": [r.name for r in report.repos if r.result == "updated"],
        "already_current": [r.name for r in report.repos if r.result == "already current"],
        "skipped_non_repo_folders": skipped_non_repo,
        "skipped_dirty_repos": skipped_dirty,
        "skipped_remote_issues": skipped_remote,
        "skipped_other": [r.name for r in report.repos
                          if r.result.startswith("skip:") and r.name not in known],
        "failed": [r.name for r in report.repos if r.result.startswith("failed:")],
    }


def print_summary(report: RootReport, *, stream=None) -> None:
    emit = partial(print, file=stream)
    summary = build_summary(report)
    emit("Summary:")
    print_list("  Updated", summary["updated"], stream=stream)
    print_list("  Already current", summary["already_current"], stream=stream)
    print_list("  Skipped non-repo folders", summary["skipped_non_repo_folders"], stream=stream)
    print_list("  Skipped dirty repos", summary["skipped_dirty_repos"], stream=stream)
    print_list("  Skipped remote issues", summary["skipped_remote_issues"], stream=stream)
    print_list("  Skipped other", summary["skipped_other"], stream=stream)
    print_list("  Failed", summary["failed"], stream=stream)


def report_payload(reports: list[RootReport], mode: str, approved_prefixes: list[str]) -> dict:
    return {
        "tool": APP_NAME,
        "version": VERSION,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "approved_remote_prefixes": approved_prefixes,
        "elapsed_seconds": round(sum(r.elapsed_seconds for r in reports), 3),
        "roots": [{"scan": asdict(r), "summary": build_summary(r)} for r in reports],
    }


def resolve_roots(raw_roots: list[Path] | None) -> list[Path]:
    roots = raw_roots or [Path.cwd()]
    resolved = []
    for root in roots:
        path = checked_path(root)
        if not path.exists() or not path.is_dir():
            raise ValueError(f"root is not a directory: {path}")
        resolved.append(path)
    return resolved
