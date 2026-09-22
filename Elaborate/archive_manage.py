"""
Archive Manager
===============

Look after a set of archive folders across time: register them, give each a double-clickable
`update_archive` launcher, refresh them all at once, and (on Windows) on a monthly schedule.

This is an *Elaborate* operation because it reaches across time: a scheduled refresh fires
while you are asleep. That is exactly why automated runs only ever use an archive's configured
`--update` or `--sync` verb and never `--reconcile`, `--rename-folders` or `--publish` -- those
stay interactive, in `Special/archive_sync.py`, where a person is watching.

Run with no arguments to use the menu (on Windows, a folder picker is offered):

    python Elaborate/archive_manage.py

Command-line usage:

    python Elaborate/archive_manage.py --install /path/to/archive [--mode update|sync]
    python Elaborate/archive_manage.py --list | --status
    python Elaborate/archive_manage.py --forget /path/to/archive
    python Elaborate/archive_manage.py --refresh-all [--scan-only] [--force-sync]
    python Elaborate/archive_manage.py --write-refresh-all-script
    python Elaborate/archive_manage.py --install-monthly-task | --task-status | --remove-task

State lives in the per-user gitSpecOps folder (`GITSPECOPS_HOME` overrides it): the registry
`gitspecops_managed_archives.json`, the log `archive_manage.log`, and the refresh-all launcher
`refresh_managed_archives`, which is what a scheduled task runs.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from _os.current import launcher, schedule  # noqa: E402
from Basic._confirm import confirm_typed, prompt_input, prompt_yes_no  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._discovery import list_child_dirs  # noqa: E402
from Basic._facts import is_repo_root  # noqa: E402
from Basic._paths import config_home  # noqa: E402
from Elaborate._archive_registry import (  # noqa: E402
    InstallRecord,
    forget_installation,
    load_registry,
    registry_path,
    save_registry,
    upsert_record,
)
from Special import archive_sync  # noqa: E402
from Special._archive_plan import (  # noqa: E402
    DEFAULT_APPROVED_REMOTE_PREFIXES,
    approved_remote,
    inspect_candidate,
)
from Special.archive_sync import (  # noqa: E402
    DEFAULT_REPORT_DIR,
    apply_clone,
    apply_pull,
    apply_reconcile_origins,
    apply_rename_folders,
    detect_plan,
    render_plan,
    review,
)

#: Writes launchers into archive folders and fast-forwards their repositories. Never pushes.
EFFECT = "local"

APP_NAME = "Archive Manager"
VERSION = "0.4.0"
REPO_ROOT = Path(_ROOT)

# Per-archive run modes baked into the launcher / stored in the registry.
MODE_UPDATE = "update"   # fast-forward pull only (safe; default)
MODE_SYNC = "sync"       # update + clone repos missing locally (additive)
VALID_MODES = (MODE_UPDATE, MODE_SYNC)

ARCHIVE_LAUNCHER = "update_archive"            # written into each archive folder
REFRESH_ALL_LAUNCHER = "refresh_managed_archives"  # written into the per-user state folder
DEFAULT_TASK_NAME = "gitSpecOps Archive Refresh"
SYNC_SCRIPT = "Special/archive_sync.py"
MANAGE_SCRIPT = "Elaborate/archive_manage.py"


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_path() -> Path:
    return config_home() / "archive_manage.log"


def log_event(message: str) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now_stamp()}] {message}\n")


# --------------------------------------------------------------------------------------
# Validating an archive folder
# --------------------------------------------------------------------------------------
def _suitable(repo, approved_prefixes: list[str]) -> bool:
    return repo.is_work_tree and repo.origin_present and approved_remote(repo.origin, approved_prefixes)


def scan_suitable_repos_with_progress(root: Path, approved_prefixes: list[str]) -> list[str]:
    child_dirs = list_child_dirs(root)
    suitable: list[str] = []
    print(f"Scanning direct child folders: {len(child_dirs)} candidate(s)")
    if not child_dirs:
        print("  none")
        return suitable
    for index, path in enumerate(child_dirs, start=1):
        print(f"  [{index}/{len(child_dirs)}] {path.name} ... ", end="", flush=True)
        repo = inspect_candidate(path, approved_prefixes)
        if _suitable(repo, approved_prefixes):
            suitable.append(repo.name)
            print("suitable")
        elif repo.is_work_tree:
            print(repo.action.removeprefix("skip: "))
        else:
            print("not a repo")
    print(f"Scan complete: {len(suitable)} suitable repo(s) found.")
    return suitable


def validate_archive_root(root: Path, approved_prefixes: list[str],
                          show_progress: bool = False) -> tuple[Path, list[str]]:
    resolved = root.resolve()
    if show_progress:
        print(f"Accepted archive folder: {resolved}")
        print("Beginning archive validation scan...")
        print()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"target folder is not a directory: {resolved}")
    if is_repo_root(resolved):
        raise ValueError(f"target folder is itself a Git repository: {resolved}")
    if show_progress:
        suitable = scan_suitable_repos_with_progress(resolved, approved_prefixes)
    else:
        suitable = [repo.name for repo in (inspect_candidate(path, approved_prefixes)
                                           for path in list_child_dirs(resolved))
                    if _suitable(repo, approved_prefixes)]
    if not suitable:
        raise ValueError("target folder must contain at least one direct child Git repository "
                         "with an approved origin remote")
    return resolved, suitable


# --------------------------------------------------------------------------------------
# What automated runs execute. Only --update or --sync, ever.
# --------------------------------------------------------------------------------------
def automated_sync_args(root: Path | str, approved_prefixes: list[str], mode: str) -> list[str]:
    """archive_sync arguments for an unattended run of one archive: its verb, --yes, prefixes."""
    args = ["--root", str(root), "--sync" if mode == MODE_SYNC else "--update", "--yes"]
    for prefix in approved_prefixes:
        args += ["--approved-remote-prefix", prefix]
    return args


def install_launchers(root: Path, approved_prefixes: list[str], show_progress: bool = False,
                      prevalidated_repos: list[str] | None = None,
                      mode: str = MODE_UPDATE) -> InstallRecord:
    if prevalidated_repos is None:
        resolved, repos = validate_archive_root(root, approved_prefixes, show_progress=show_progress)
    else:
        resolved, repos = root.resolve(), prevalidated_repos
    if show_progress:
        print()
        print(f"Writing archive launcher ({mode}) into: {resolved}")
    written = launcher.write_launcher(resolved, ARCHIVE_LAUNCHER, REPO_ROOT, SYNC_SCRIPT,
                                      automated_sync_args(resolved, approved_prefixes, mode))
    launcher_type = "+".join(p.suffix.lstrip(".")
                             for p in launcher.launcher_files(resolved, ARCHIVE_LAUNCHER))
    stamp = now_stamp()
    record = InstallRecord(
        root=str(resolved),
        installed_at=stamp,
        updated_at=stamp,
        git_spec_ops_dir=str(REPO_ROOT),
        python_executable=str(Path(sys.executable).resolve()),
        runner=f"{SYNC_SCRIPT} ({mode})",
        launcher=str(written),
        launcher_type=launcher_type,
        repo_count=len(repos),
        approved_remote_prefixes=approved_prefixes,
        mode=mode,
    )
    upsert_record(record)
    if show_progress:
        print(f"Registry updated: {registry_path()}")
        print(f"Install complete: {len(repos)} suitable repo(s) registered.")
    log_event(f"installed archive root={resolved} launcher={written} repos={len(repos)}")
    return record


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------
def installation_status(item: dict) -> dict:
    root = Path(item["root"])
    launcher_file = Path(item.get("launcher", ""))
    report_dir = root / DEFAULT_REPORT_DIR
    reports = sorted(report_dir.glob("archive-update-*.json")) if report_dir.exists() else []
    latest = reports[-1] if reports else None
    return {
        "root": str(root),
        "root_exists": root.is_dir(),
        "launcher_exists": launcher_file.is_file(),
        "launcher": str(launcher_file),
        "launcher_type": item.get("launcher_type", "unknown"),
        "repo_count_at_install": item.get("repo_count", 0),
        "last_run_at": item.get("last_run_at"),
        "last_run_result": item.get("last_run_result"),
        "last_run_elapsed_seconds": item.get("last_run_elapsed_seconds"),
        "last_report": item.get("last_report"),
        "latest_report": str(latest) if latest else None,
        "latest_report_at": (datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds")
                             if latest else None),
        "installed_at": item.get("installed_at"),
        "updated_at": item.get("updated_at"),
    }


def print_registry(show_status: bool) -> None:
    installations = load_registry()["installations"]
    print(f"{APP_NAME} v{VERSION}")
    print(f"Registry: {registry_path()}")
    print(f"Installations: {len(installations)}")
    for item in installations:
        details = installation_status(item) if show_status else item
        print()
        print(f"Root: {details['root']}")
        print(f"  mode: {item.get('mode', 'update')}")
        print(f"  installed: {details.get('installed_at', 'unknown')}")
        print(f"  updated: {details.get('updated_at', 'unknown')}")
        if show_status:
            print(f"  root exists: {'yes' if details['root_exists'] else 'no'}")
            print(f"  launcher exists: {'yes' if details['launcher_exists'] else 'no'}")
            print(f"  launcher type: {details['launcher_type']}")
            print(f"  repos at install: {details['repo_count_at_install']}")
            print(f"  last run: {details.get('last_run_at') or 'never'}")
            print(f"  last result: {details.get('last_run_result') or 'unknown'}")
            print(f"  last elapsed: {details.get('last_run_elapsed_seconds') or 'unknown'}")
            print(f"  latest report: {details.get('latest_report') or 'none'}")
        else:
            print(f"  launcher: {details['launcher']}")
            print(f"  repos at install: {details['repo_count']}")


def print_dashboard() -> None:
    installations = load_registry()["installations"]
    print("=" * 60)
    print(f"{APP_NAME} v{VERSION}")
    print("=" * 60)
    print(f"Registry: {registry_path()}")
    print(f"Managed archives: {len(installations)}")
    print()
    if not installations:
        print("No managed archives yet.")
        print()
        return
    for index, item in enumerate(installations, start=1):
        details = installation_status(item)
        print(f"{index}. {details['root']}")
        print(f"   mode: {item.get('mode', 'update')}")
        print(f"   repos at install: {details['repo_count_at_install']}")
        print(f"   root: {'ok' if details['root_exists'] else 'missing'}")
        print(f"   launcher: {'ok' if details['launcher_exists'] else 'missing'} ({details['launcher_type']})")
        print(f"   installed: {details.get('installed_at') or 'unknown'}")
        print(f"   last run: {details.get('last_run_at') or 'never'}")
        print(f"   last result: {details.get('last_run_result') or 'unknown'}")
        print(f"   last elapsed: {details.get('last_run_elapsed_seconds') or 'unknown'}")
        print(f"   latest report: {details.get('latest_report_at') or 'none'}")
        print()


# --------------------------------------------------------------------------------------
# Refreshing every managed archive, in-process
# --------------------------------------------------------------------------------------
def refresh_argv(item: dict, scan_only: bool, force_sync: bool = False) -> list[str]:
    """archive_sync arguments for one registered archive in a refresh-all run."""
    prefixes = item.get("approved_remote_prefixes") or DEFAULT_APPROVED_REMOTE_PREFIXES
    if scan_only:
        argv = ["--root", str(item["root"])]
        for prefix in prefixes:
            argv += ["--approved-remote-prefix", prefix]
        return argv  # no verb -> archive_sync reports only
    # Each archive runs its configured mode; force_sync promotes all to sync for this run.
    mode = MODE_SYNC if (force_sync or item.get("mode") == MODE_SYNC) else MODE_UPDATE
    return automated_sync_args(item["root"], prefixes, mode)


def _run_sync(argv: list[str]) -> int:
    """archive_sync.main in this process. One archive's failure must not stop the others."""
    try:
        return archive_sync.main(argv)
    except SystemExit as exc:  # argparse, or a deliberate exit inside the run
        return exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001 - collected, reported, and the run moves on
        print(f"failed: {exc.__class__.__name__}: {exc}")
        return 1


def refresh_all(scan_only: bool, force_sync: bool = False) -> int:
    started_all = time.perf_counter()
    data = load_registry()
    installations = data["installations"]
    if not installations:
        print("No managed archives to refresh.")
        return 0

    failures = refreshed = 0
    latest_reports: list[str] = []
    mode = "scan-only" if scan_only else ("sync (all forced)" if force_sync else "per-archive mode")
    print(f"Refreshing {len(installations)} managed archive(s): {mode}.")
    log_event(f"refresh-all started mode={mode} count={len(installations)}")
    print()

    for item in installations:
        root = item["root"]
        started = time.perf_counter()
        print("=" * 60)
        print(f"Archive: {root}")
        print("=" * 60)
        if not Path(root).exists():
            item["last_run_at"] = now_stamp()
            item["last_run_result"] = "failed: root missing"
            item["last_run_elapsed_seconds"] = round(time.perf_counter() - started, 3)
            failures += 1
            print("failed: root missing")
            log_event(f"refresh failed root={root} reason=root missing")
            continue

        code = _run_sync(refresh_argv(item, scan_only, force_sync))
        elapsed = round(time.perf_counter() - started, 3)
        status = "ok" if code == 0 else f"failed: exit {code}"
        details = installation_status(item)
        item["last_run_at"] = now_stamp()
        item["last_run_result"] = status
        item["last_run_elapsed_seconds"] = elapsed
        item["last_report"] = details.get("latest_report")
        item["last_report_at"] = details.get("latest_report_at")
        if code:
            failures += 1
        else:
            refreshed += 1
        if details.get("latest_report"):
            latest_reports.append(details["latest_report"])
        print(f"Archive refresh result: {status} ({elapsed:.3f}s)")
        log_event(f"refresh result root={root} status={status} elapsed={elapsed}s "
                  f"report={details.get('latest_report') or 'none'}")
        print()

    save_registry(data)
    elapsed_all = round(time.perf_counter() - started_all, 3)
    print("=" * 60)
    print("Refresh Summary")
    print("=" * 60)
    print(f"Mode: {mode}")
    print(f"Managed archives: {len(installations)}")
    print(f"Succeeded: {refreshed}")
    print(f"Failed: {failures}")
    print(f"Elapsed: {elapsed_all:.3f}s")
    if latest_reports:
        print("Latest reports:")
        for report in latest_reports:
            print(f"  - {report}")
    log_event(f"refresh-all complete mode={mode} succeeded={refreshed} failed={failures} "
              f"elapsed={elapsed_all}s")
    return 1 if failures else 0


# --------------------------------------------------------------------------------------
# The refresh-all launcher and its schedule
# --------------------------------------------------------------------------------------
def write_refresh_all_script() -> Path:
    """Write the refresh-all launcher into the per-user state folder and return what to run.

    It lives outside the checkout on purpose: a scheduled task points at it, and that path must
    not change when the code is reorganized. It carries the checkout's location instead.
    """
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    path = launcher.write_launcher(home, REFRESH_ALL_LAUNCHER, REPO_ROOT, MANAGE_SCRIPT,
                                   ["--refresh-all"])
    log_event(f"wrote refresh-all script path={path}")
    return path


def install_monthly_task(task_name: str, day: int, time_of_day: str) -> int:
    script = write_refresh_all_script()
    code = schedule.install_monthly(task_name, script, day, time_of_day)
    log_event(f"schedule monthly task name={task_name} day={day} time={time_of_day} "
              f"script={script} exit={code}")
    return code


def task_status(task_name: str) -> int:
    return schedule.status(task_name)


def remove_task(task_name: str) -> int:
    code = schedule.remove(task_name)
    log_event(f"remove scheduled task name={task_name} exit={code}")
    return code


# --------------------------------------------------------------------------------------
# The menu
# --------------------------------------------------------------------------------------
def choose_folder_dialog() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Choose archive folder to manage")
    root.destroy()
    return Path(folder) if folder else None


def _install_interactively(approved_prefixes: list[str]) -> None:
    path_text = prompt_input("Archive folder path (blank opens picker): ")
    target = Path(path_text) if path_text else choose_folder_dialog()
    if not target:
        print("No archive folder selected.")
        return
    target = target.resolve()
    if not target.is_dir():
        print(f"Not a directory: {target}")
        return

    # DETECT + PLAN: scan local + (if a provider matches) the authoritative remote set.
    print(f"Scanning {target} ...")
    result = detect_plan(target, approved_prefixes)
    render_plan(result)
    issues = list(result.errors)
    plan = result.plan

    # DECIDE + EXECUTE, bulk, human in the middle. Nothing applied without an explicit yes.
    if plan.to_clone and prompt_yes_no(f"Clone {len(plan.to_clone)} missing repo(s) now?", default=False):
        apply_clone(target, plan, issues)
    stale = [it for it in plan.to_reconcile if it.origin_stale]
    if stale and prompt_yes_no(f"Rewrite {len(stale)} stale origin URL(s)?", default=False):
        apply_reconcile_origins(target, plan, issues)
    drift = [it for it in plan.to_reconcile if it.folder_mismatch]
    if drift and prompt_yes_no(f"Rename {len(drift)} folder(s) to match upstream?", default=False):
        apply_rename_folders(target, plan, issues)
    if plan.to_pull and prompt_yes_no(f"Fast-forward {len(plan.to_pull)} repo(s) now?", default=False):
        apply_pull(target, plan, issues)
    print()
    review(issues)
    print()

    # CONFIGURE: the verb future (and scheduled) runs of this archive will use. Sync is offered
    # only with an authoritative remote listing; without one there is nothing to clone.
    mode = MODE_UPDATE
    if result.provider_name is not None and result.remote_authoritative:
        answer = prompt_input("Mode for automated runs - [u]pdate-only (safe) or [s]ync "
                              "(auto-clone new)? [U/s]: ").lower()
        mode = MODE_SYNC if answer in ("s", "sync") else MODE_UPDATE
    try:
        record = install_launchers(target, approved_prefixes, show_progress=True, mode=mode)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}")
        return
    print(f"Installed archive launcher for {record.root}")
    print(f"  Launcher: {record.launcher}  (mode: {record.mode})")
    print(f"  Registry: {registry_path()}")


def interactive_menu(approved_prefixes: list[str]) -> int:
    while True:
        print_dashboard()
        print("Actions:")
        print("  1. Install or refresh an archive launcher")
        print("  2. Scan all managed archives")
        print("  3. Update all managed archives")
        print("  4. Show detailed status")
        print("  5. Write refresh-all script")
        print("  6. Create monthly scheduled refresh")
        print("  7. Show scheduled refresh status")
        print("  8. Remove scheduled refresh")
        print("  Q. Quit")
        print()
        choice = prompt_input("Choice: ").lower()
        print()

        if choice == "1":
            _install_interactively(approved_prefixes)
        elif choice == "2":
            refresh_all(scan_only=True)
        elif choice == "3":
            if confirm_typed("YES", 'Type "YES" to refresh all managed archives: '):
                # Each archive runs its own configured mode. This promotes ALL of them to sync.
                force_sync = prompt_yes_no("Force SYNC (clone missing) for EVERY archive, "
                                           "overriding per-archive mode?", default=False)
                refresh_all(scan_only=False, force_sync=force_sync)
            else:
                print("Skipped.")
        elif choice == "4":
            print_registry(show_status=True)
            print()
            prompt_input("Press ENTER to continue...")
        elif choice == "5":
            print(f"Wrote refresh-all script: {write_refresh_all_script()}")
        elif choice == "6":
            task_name = prompt_input(f"Task name [{DEFAULT_TASK_NAME}]: ") or DEFAULT_TASK_NAME
            day_text = prompt_input("Day of month [1]: ") or "1"
            time_text = prompt_input("Start time HH:MM [09:00]: ") or "09:00"
            try:
                day = int(day_text)
            except ValueError:
                print("Invalid day.")
                print()
                continue
            code = install_monthly_task(task_name, day, time_text)
            print("Scheduled task created." if code == 0 else f"Scheduled task failed with exit {code}.")
        elif choice == "7":
            task_name = prompt_input(f"Task name [{DEFAULT_TASK_NAME}]: ") or DEFAULT_TASK_NAME
            code = task_status(task_name)
            if code != 0:
                print(f"Scheduled task query failed with exit {code}.")
        elif choice == "8":
            task_name = prompt_input(f"Task name [{DEFAULT_TASK_NAME}]: ") or DEFAULT_TASK_NAME
            if confirm_typed("YES", f'Type "YES" to remove scheduled task "{task_name}": '):
                code = remove_task(task_name)
                print("Scheduled task removed." if code == 0
                      else f"Scheduled task removal failed with exit {code}.")
            else:
                print("Skipped.")
        elif choice in {"q", "quit", "exit"}:
            return 0
        else:
            print("Unknown choice.")
        print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register archive folders, give each a launcher, "
                                                 "and refresh them together or on a schedule.")
    parser.add_argument("--install", type=Path, help="Archive folder where a launcher should be created.")
    parser.add_argument("--mode", choices=VALID_MODES, default=MODE_UPDATE,
                        help="With --install: launcher verb for automated runs. 'update' (safe) or "
                             "'sync' (auto-clone).")
    parser.add_argument("--list", action="store_true", help="List registered archives.")
    parser.add_argument("--status", action="store_true", help="List archives and verify paths still exist.")
    parser.add_argument("--forget", type=Path, help="Remove one archive folder from the registry.")
    parser.add_argument("--refresh-all", action="store_true", help="Run archive sync for every managed archive.")
    parser.add_argument("--scan-only", action="store_true", help="Use scan-only mode with --refresh-all.")
    parser.add_argument("--force-sync", action="store_true",
                        help="Promote every archive to sync for this --refresh-all run.")
    parser.add_argument("--write-refresh-all-script", action="store_true",
                        help="Write the refresh-all launcher into the per-user state folder.")
    parser.add_argument("--install-monthly-task", action="store_true",
                        help="Create/update a monthly scheduled refresh (Windows Task Scheduler).")
    parser.add_argument("--task-status", action="store_true", help="Show the scheduled refresh.")
    parser.add_argument("--remove-task", action="store_true", help="Remove the scheduled refresh.")
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME, help="Scheduled task name.")
    parser.add_argument("--task-day", type=int, default=1, help="Day of month for --install-monthly-task.")
    parser.add_argument("--task-time", default="09:00", help="Start time for --install-monthly-task in HH:MM.")
    parser.add_argument("--approved-remote-prefix", action="append",
                        help="Allowed origin prefix. Repeatable. Defaults to the common GitHub forms.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    enable_unicode_output()
    args = parse_args(argv)
    approved_prefixes = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES
    try:
        if args.refresh_all:
            return refresh_all(scan_only=args.scan_only, force_sync=args.force_sync)
        if args.write_refresh_all_script:
            print(f"Wrote refresh-all script: {write_refresh_all_script()}")
            return 0
        if args.install_monthly_task:
            return install_monthly_task(args.task_name, args.task_day, args.task_time)
        if args.task_status:
            return task_status(args.task_name)
        if args.remove_task:
            return remove_task(args.task_name)
        if args.list or args.status:
            print_registry(show_status=args.status)
            return 0
        if args.forget:
            removed = forget_installation(args.forget)
            if removed:
                log_event(f"forgot archive root={args.forget.resolve()}")
            print("Removed from registry." if removed else "No matching registry entry found.")
            return 0 if removed else 1
        if not args.install:
            return interactive_menu(approved_prefixes)
        record = install_launchers(args.install, approved_prefixes, show_progress=True, mode=args.mode)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error writing launcher or registry: {exc}", file=sys.stderr)
        return 3

    print(f"Installed archive launcher for {record.root}  (mode: {record.mode})")
    print(f"  Launcher: {record.launcher}")
    print(f"  Registry: {registry_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
