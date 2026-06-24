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

Local repo facts come from git_inspect; this file is just scan + fast-forward + report.

Usage:
    python archive_updater.py                      # update the current folder
    python archive_updater.py --scan-only          # inventory only
    python archive_updater.py --root T:\\Github\\Archive
    python archive_updater.py --root A --root B     # several roots
    python archive_updater.py --output-dir REPORTS  # write a dated JSON report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

try:
    from .git_inspect import (
        RepoInfo,
        inspect_candidate,
        is_hidden,
        list_child_dirs,
        run_git,
        set_git_timeout,
    )
except ImportError:
    from git_inspect import (
        RepoInfo,
        inspect_candidate,
        is_hidden,
        list_child_dirs,
        run_git,
        set_git_timeout,
    )

APP_NAME = "Archive Updater"
VERSION = "0.4.0"
DEFAULT_APPROVED_REMOTE_PREFIXES = ["https://github.com/", "git@github.com:", "ssh://git@github.com/"]
DEFAULT_GIT_TIMEOUT_SECONDS = 45


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


def scan_root(root: Path, approved_prefixes: list[str]) -> RootReport:
    started = time.perf_counter()
    child_dirs = list_child_dirs(root)
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
    )
    report.elapsed_seconds = round(time.perf_counter() - started, 3)
    return report


def print_list(title: str, names: list[str]) -> None:
    print(f"{title}: {len(names)}")
    for name in names:
        print(f"  - {name}")
    if not names:
        print("  - none")


def print_scan(report: RootReport, show_remote_urls: bool) -> None:
    print(f"Scan Root: {report.root}")
    print(f"Generated: {report.generated}")
    print(f"Scan time: {report.elapsed_seconds:.3f}s")
    print()
    print_list("Git repositories", report.git_repositories)
    print_list("Non-repo folders", report.non_repo_folders)
    print()
    print("Candidate details:")
    for repo in report.repos:
        origin = repo.origin if (repo.origin and show_remote_urls) else ("present" if repo.origin_present else "none")
        print(f"  {repo.name}: work_tree={'yes' if repo.is_work_tree else 'no'} "
              f"host={repo.host or '-'} branch={repo.branch or '-'} "
              f"dirty={'yes' if repo.dirty_work_tree or repo.dirty_index else 'no'} "
              f"origin={origin} action={repo.action}")
    print()


def update_repo(repo: RepoInfo) -> str:
    path = Path(repo.path)
    fetch = run_git(path, ["fetch", "--dry-run", "origin"])
    if fetch.returncode != 0:
        detail = f": {fetch.stderr.strip()}" if fetch.stderr.strip() else ""
        return f"failed: fetch failed{detail}"
    pull = run_git(path, ["pull", "--ff-only"])
    if pull.returncode != 0:
        detail = f": {pull.stderr.strip()}" if pull.stderr.strip() else ""
        return f"failed: pull --ff-only failed{detail}"
    combined = f"{pull.stdout}\n{pull.stderr}".lower()
    if "already up to date" in combined or "already up-to-date" in combined:
        return "already current"
    return "updated"


def run_updates(report: RootReport) -> None:
    for repo in report.repos:
        if repo.eligible:
            print(f"[PULL] {repo.name}")
            started = time.perf_counter()
            repo.result = update_repo(repo)
            repo.elapsed_seconds = round(time.perf_counter() - started, 3)
            print(f"       {repo.result} ({repo.elapsed_seconds:.3f}s)")
        else:
            repo.result = repo.action
            print(f"[SKIP] {repo.name} - {repo.action.removeprefix('skip: ')}")


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


def print_summary(report: RootReport) -> None:
    summary = build_summary(report)
    print("Summary:")
    print_list("  Updated", summary["updated"])
    print_list("  Already current", summary["already_current"])
    print_list("  Skipped non-repo folders", summary["skipped_non_repo_folders"])
    print_list("  Skipped dirty repos", summary["skipped_dirty_repos"])
    print_list("  Skipped remote issues", summary["skipped_remote_issues"])
    print_list("  Skipped other", summary["skipped_other"])
    print_list("  Failed", summary["failed"])


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


def write_report(output_dir: Path, reports: list[RootReport], mode: str, approved_prefixes: list[str]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = output_dir / f"archive-update-{stamp}.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report_payload(reports, mode, approved_prefixes), handle, indent=2)
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan and fast-forward update one or more folders of sibling Git repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="For clone/rename/sync of an org's repos, use archive_sync.py.",
    )
    parser.add_argument("--root", type=Path, action="append", help="Folder to scan. Repeatable. Defaults to cwd.")
    parser.add_argument("--scan-only", action="store_true", help="Only scan and report; do not pull.")
    parser.add_argument("--output-dir", type=Path, help="Folder for one dated JSON report covering all roots.")
    parser.add_argument("--default-output-dir", type=Path, help="Per-root relative output folder when --output-dir is omitted.")
    parser.add_argument("--approved-remote-prefix", action="append",
                        help="Allowed origin prefix. Repeatable. Defaults to common GitHub forms.")
    parser.add_argument("--show-remote-urls", action="store_true", help="Print full origin URLs.")
    parser.add_argument("--no-report", action="store_true", help="Do not write a dated JSON report.")
    parser.add_argument("--git-timeout", type=int, default=DEFAULT_GIT_TIMEOUT_SECONDS,
                        help=f"Per-git-command timeout seconds. Default {DEFAULT_GIT_TIMEOUT_SECONDS}.")
    # Deprecated discovery flags: accepted for backward compatibility with older launchers.
    parser.add_argument("--github-owner", help=argparse.SUPPRESS)
    parser.add_argument("--clone-new", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-clone-new", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def resolve_roots(raw_roots: list[Path] | None) -> list[Path]:
    roots = raw_roots or [Path.cwd()]
    resolved = []
    for root in roots:
        path = root.resolve()
        if not path.exists() or not path.is_dir():
            raise ValueError(f"root is not a directory: {path}")
        resolved.append(path)
    return resolved


def resolve_output_dir(args: argparse.Namespace, roots: list[Path]) -> Path | None:
    if args.no_report:
        return None
    if args.output_dir:
        return args.output_dir.resolve()
    if args.default_output_dir and len(roots) == 1:
        return (roots[0] / args.default_output_dir).resolve()
    if args.default_output_dir and len(roots) > 1:
        raise ValueError("--default-output-dir can only be used with a single --root")
    return None


def main() -> int:
    started = time.perf_counter()
    args = parse_args()
    set_git_timeout(args.git_timeout)
    approved_prefixes = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES

    if args.github_owner or args.clone_new:
        print("Note: repo discovery/clone/rename moved to archive_sync.py. "
              "Updating local repos only. For full sync run:")
        print(f"      python archive_sync.py --root <folder> --sync")
        print()

    try:
        roots = resolve_roots(args.root)
        output_dir = resolve_output_dir(args, roots)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    mode = "scan-only" if args.scan_only else "update"
    reports: list[RootReport] = []
    print(f"{APP_NAME} v{VERSION}")
    print(f"Mode: {mode}")
    print(f"Roots: {len(roots)}")
    print()

    for index, root in enumerate(roots, start=1):
        if len(roots) > 1:
            print(f"Root {index} of {len(roots)}")
        report = scan_root(root, approved_prefixes)
        reports.append(report)
        print_scan(report, show_remote_urls=args.show_remote_urls)
        if args.scan_only:
            print("Scan only: no repositories were updated.")
        else:
            run_updates(report)
            print()
            print_summary(report)
        print()

    if output_dir:
        print(f"Report: {write_report(output_dir, reports, mode, approved_prefixes)}")
    else:
        print("Report: not written; pass --output-dir or --default-output-dir to write one.")
    print(f"Elapsed: {time.perf_counter() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
