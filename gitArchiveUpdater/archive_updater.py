"""
Archive Updater
===============

Purpose
-------
Scan one or more local folders that contain sibling Git repositories, print a
clear inventory of what was found, and optionally update eligible repositories
with `git pull --ff-only`.

This tool is intentionally conservative:
- It only inspects direct child folders of each root.
- It never merges, rebases, resets, force-pushes, installs dependencies, or
  runs project code.
- It updates only clean Git work trees whose `origin` remote starts with an
  approved prefix, defaulting to `https://github.com/`.
- It writes dated JSON reports when an output folder is configured.

Typical Usage
-------------
Run from the folder you want to manage:

    uv run python gitArchiveUpdater\\archive_updater.py

Scan without fetching or pulling:

    uv run python gitArchiveUpdater\\archive_updater.py --scan-only

Point at one folder:

    uv run python gitArchiveUpdater\\archive_updater.py --root T:\\Github\\Archive

Point at several folders:

    uv run python gitArchiveUpdater\\archive_updater.py --root T:\\Github\\Archive --root T:\\Github\\BonusBrain

Write dated reports somewhere explicit:

    uv run python gitArchiveUpdater\\archive_updater.py --root T:\\Github\\Archive --output-dir T:\\Github\\Archive\\.gitSpecOps\\archive-updates

Show full remote URLs in console output:

    uv run python gitArchiveUpdater\\archive_updater.py --show-remote-urls

Parameters
----------
--root PATH
    Root folder to scan. May be passed more than once. Defaults to the current
    working directory when omitted.

--output-dir PATH
    Folder where dated JSON reports are written. If omitted, no report is
    written unless `--default-output-dir NAME` is used.

--default-output-dir NAME
    For each scanned root, write reports under ROOT/NAME. Example:
    `--default-output-dir .gitSpecOps/archive-updates`.

--scan-only
    Inventory only. No fetch or pull.

--approved-remote-prefix PREFIX
    Allowed remote prefix. May be passed more than once. Defaults to
    `https://github.com/`.

--show-remote-urls
    Print full remote URLs. By default, console output only says whether an
    origin is present to avoid leaking credentials embedded in URLs.

--no-report
    Suppress report writing even if an output directory is configured.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


APP_NAME = "Archive Updater"
VERSION = "0.2.0"
DEFAULT_APPROVED_REMOTE_PREFIXES = ["https://github.com/"]
DEFAULT_GIT_TIMEOUT_SECONDS = 45
GIT_TIMEOUT_SECONDS = DEFAULT_GIT_TIMEOUT_SECONDS


@dataclass
class RepoInfo:
    name: str
    path: str
    hidden: bool
    has_git_marker: bool
    is_work_tree: bool
    origin_present: bool
    origin: str | None
    approved_remote: bool
    branch: str | None
    dirty_work_tree: bool
    dirty_index: bool
    eligible: bool
    action: str
    result: str = "not run"
    elapsed_seconds: float = 0.0


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


def run_git(repo_path: Path, args: Iterable[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    timeout = GIT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (PermissionError, FileNotFoundError):
        return subprocess.CompletedProcess(list(args), returncode=1, stdout="", stderr="")
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            list(args),
            returncode=124,
            stdout=exc.stdout or "",
            stderr=f"timed out after {timeout}s",
        )


def git_stdout(repo_path: Path, args: Iterable[str]) -> str | None:
    proc = run_git(repo_path, args)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def git_top_level(path: Path) -> Path | None:
    top_level = git_stdout(path, ["rev-parse", "--show-toplevel"])
    if not top_level:
        return None
    return Path(top_level).resolve()


def is_repo_root(path: Path) -> bool:
    top_level = git_top_level(path)
    return top_level == path.resolve()


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def list_child_dirs(root: Path) -> list[Path]:
    return sorted(
        [item for item in root.iterdir() if item.is_dir()],
        key=lambda item: item.name.lower(),
    )


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
        approved_remote=origin_ok,
        branch=branch,
        dirty_work_tree=dirty_work_tree,
        dirty_index=dirty_index,
        eligible=action.startswith("eligible:"),
        action=action,
        elapsed_seconds=round(time.perf_counter() - started, 3),
    )


def scan_root(root: Path, approved_prefixes: list[str]) -> RootReport:
    started = time.perf_counter()
    child_dirs = list_child_dirs(root)
    repos = [inspect_candidate(path, approved_prefixes) for path in child_dirs]

    report = RootReport(
        root=str(root),
        generated=datetime.now().isoformat(timespec="seconds"),
        hidden_folders=[path.name for path in child_dirs if is_hidden(path)],
        regular_folders=[path.name for path in child_dirs if not is_hidden(path)],
        candidate_folders=[path.name for path in child_dirs],
        git_repositories=[repo.name for repo in repos if repo.is_work_tree],
        non_repo_folders=[repo.name for repo in repos if not repo.is_work_tree],
        repos=repos,
    )
    report.elapsed_seconds = round(time.perf_counter() - started, 3)
    return report


def print_list(title: str, names: list[str]) -> None:
    print(f"{title}: {len(names)}")
    if names:
        for name in names:
            print(f"  - {name}")
    else:
        print("  - none")


def print_scan(report: RootReport, show_remote_urls: bool) -> None:
    print(f"Scan Root: {report.root}")
    print(f"Generated: {report.generated}")
    print(f"Scan time: {report.elapsed_seconds:.3f}s")
    print()
    print_list("Hidden folders", report.hidden_folders)
    print_list("Regular folders", report.regular_folders)
    print_list("Candidate folders", report.candidate_folders)
    print_list("Git repositories", report.git_repositories)
    print_list("Non-repo folders", report.non_repo_folders)
    print()

    print("Candidate details:")
    for repo in report.repos:
        print(f"  {repo.name}")
        print(f"    .git marker: {'yes' if repo.has_git_marker else 'no'}")
        print(f"    work tree: {'yes' if repo.is_work_tree else 'no'}")
        if repo.origin and show_remote_urls:
            print(f"    origin: {repo.origin}")
        elif repo.origin_present:
            print("    origin: present")
        else:
            print("    origin: none")
        print(f"    approved remote: {'yes' if repo.approved_remote else 'no'}")
        print(f"    branch: {repo.branch or 'unknown'}")
        print(f"    dirty work tree: {'yes' if repo.dirty_work_tree else 'no'}")
        print(f"    dirty index: {'yes' if repo.dirty_index else 'no'}")
        print(f"    action: {repo.action}")
        print(f"    inspect time: {repo.elapsed_seconds:.3f}s")
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
    skipped_dirty_actions = {
        "skip: working tree has local changes",
        "skip: index has staged changes",
    }
    skipped_remote_actions = {
        "skip: no origin remote",
        "skip: origin is not approved",
    }

    skipped_non_repo = [repo.name for repo in report.repos if repo.result == "skip: not a git repository"]
    skipped_dirty = [repo.name for repo in report.repos if repo.result in skipped_dirty_actions]
    skipped_remote = [repo.name for repo in report.repos if repo.result in skipped_remote_actions]
    known_skips = set(skipped_non_repo + skipped_dirty + skipped_remote)

    return {
        "updated": [repo.name for repo in report.repos if repo.result == "updated"],
        "already_current": [repo.name for repo in report.repos if repo.result == "already current"],
        "skipped_non_repo_folders": skipped_non_repo,
        "skipped_dirty_repos": skipped_dirty,
        "skipped_remote_issues": skipped_remote,
        "skipped_other": [
            repo.name
            for repo in report.repos
            if repo.result.startswith("skip:") and repo.name not in known_skips
        ],
        "failed": [repo.name for repo in report.repos if repo.result.startswith("failed:")],
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
        "git_timeout_seconds": GIT_TIMEOUT_SECONDS,
        "elapsed_seconds": round(sum(report.elapsed_seconds for report in reports), 3),
        "roots": [
            {
                "scan": asdict(report),
                "summary": build_summary(report),
            }
            for report in reports
        ],
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
        description="Scan and update one or more folders of sibling Git repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with no arguments to scan/update the current working directory.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        help="Folder to scan. May be passed more than once. Defaults to cwd.",
    )
    parser.add_argument("--scan-only", action="store_true", help="Only scan and report; do not fetch or pull.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Folder for one dated JSON report covering all scanned roots.",
    )
    parser.add_argument(
        "--default-output-dir",
        type=Path,
        help="Per-root relative output folder used when --output-dir is omitted.",
    )
    parser.add_argument(
        "--approved-remote-prefix",
        action="append",
        help="Allowed origin prefix. May be passed more than once. Defaults to https://github.com/.",
    )
    parser.add_argument("--show-remote-urls", action="store_true", help="Print full origin URLs.")
    parser.add_argument("--no-report", action="store_true", help="Do not write a dated JSON report.")
    parser.add_argument(
        "--git-timeout",
        type=int,
        default=DEFAULT_GIT_TIMEOUT_SECONDS,
        help=f"Seconds before an individual git command is treated as failed. Defaults to {DEFAULT_GIT_TIMEOUT_SECONDS}.",
    )
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
    global GIT_TIMEOUT_SECONDS
    started = time.perf_counter()
    args = parse_args()
    GIT_TIMEOUT_SECONDS = args.git_timeout
    approved_prefixes = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES

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
        report_path = write_report(output_dir, reports, mode, approved_prefixes)
        print(f"Report: {report_path}")
    else:
        print("Report: not written; pass --output-dir or --default-output-dir to write one.")

    print(f"Elapsed: {time.perf_counter() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
