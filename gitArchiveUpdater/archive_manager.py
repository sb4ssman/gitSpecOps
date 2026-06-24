"""
Archive Updater Manager
=======================

Install and track per-archive launchers that call the centralized
Archive Updater from this gitSpecOps checkout.

Run with no arguments on Windows to choose an archive folder with a dialog:

    uv run python gitArchiveUpdater\\archive_manager.py

Command-line usage:

    uv run python gitArchiveUpdater\\archive_manager.py --install T:\\Github\\Archive
    uv run python gitArchiveUpdater\\archive_manager.py --list
    uv run python gitArchiveUpdater\\archive_manager.py --status
    uv run python gitArchiveUpdater\\archive_manager.py --forget T:\\Github\\Archive
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

try:
    from .archive_updater import DEFAULT_APPROVED_REMOTE_PREFIXES
    from .git_inspect import approved_remote, inspect_candidate, is_repo_root, list_child_dirs
    from .archive_sync import (
        apply_clone,
        apply_pull,
        apply_reconcile_origins,
        apply_rename_folders,
        detect_plan,
        render_plan,
        review,
    )
except ImportError:
    from archive_updater import DEFAULT_APPROVED_REMOTE_PREFIXES
    from git_inspect import approved_remote, inspect_candidate, is_repo_root, list_child_dirs
    from archive_sync import (
        apply_clone,
        apply_pull,
        apply_reconcile_origins,
        apply_rename_folders,
        detect_plan,
        render_plan,
        review,
    )

# Per-archive run modes baked into the launcher / stored in the registry.
MODE_UPDATE = "update"   # fast-forward pull only (safe; default)
MODE_SYNC = "sync"       # update + clone repos missing locally (additive)
VALID_MODES = (MODE_UPDATE, MODE_SYNC)


APP_NAME = "Archive Updater Manager"
VERSION = "0.3.0"
TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent
REGISTRY_PATH = TOOL_DIR / "managed_archives.json"
WINDOWS = sys.platform == "win32"
LAUNCHER_NAME = "update_archive.bat" if WINDOWS else "update_archive.sh"
DEFAULT_REPORT_DIR = r".gitSpecOps\archive-updates"
REFRESH_ALL_SCRIPT = TOOL_DIR / ("refresh-managed-archives.bat" if WINDOWS else "refresh-managed-archives.sh")
DEFAULT_TASK_NAME = "gitSpecOps Archive Refresh"
RUNS_DIR = TOOL_DIR / "runs"
MANAGER_LOG = RUNS_DIR / "archive-manager.log"


@dataclass
class InstallRecord:
    root: str
    installed_at: str
    updated_at: str
    git_spec_ops_dir: str
    python_executable: str
    runner: str
    launcher: str
    launcher_type: str
    repo_count: int
    approved_remote_prefixes: list[str]
    mode: str = "update"


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_event(message: str) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    with MANAGER_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def prompt_input(prompt: str) -> str:
    """Read interactive input, ignoring VS Code auto-activation noise."""
    while True:
        value = input(prompt).strip()
        lowered = value.lower()
        if lowered.endswith(r"\scripts\activate.bat") or lowered.endswith("/bin/activate"):
            print("Ignoring terminal activation command; please enter your choice.")
            continue
        return value


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
        if repo.is_work_tree and repo.origin_present and approved_remote(repo.origin, approved_prefixes):
            suitable.append(repo.name)
            print("suitable")
        elif repo.is_work_tree:
            print(repo.action.removeprefix("skip: "))
        else:
            print("not a repo")

    print(f"Scan complete: {len(suitable)} suitable repo(s) found.")
    return suitable


def validate_archive_root(root: Path, approved_prefixes: list[str], show_progress: bool = False) -> tuple[Path, list[str]]:
    resolved = root.resolve()
    if show_progress:
        print(f"Accepted archive folder: {resolved}")
        print("Beginning archive validation scan...")
        print()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"target folder is not a directory: {resolved}")
    if is_repo_root(resolved):
        raise ValueError(f"target folder is itself a Git repository: {resolved}")

    suitable = (
        scan_suitable_repos_with_progress(resolved, approved_prefixes)
        if show_progress
        else [
            repo.name
            for repo in (inspect_candidate(path, approved_prefixes) for path in list_child_dirs(resolved))
            if repo.is_work_tree and repo.origin_present and approved_remote(repo.origin, approved_prefixes)
        ]
    )
    if not suitable:
        raise ValueError(
            "target folder must contain at least one direct child Git repository "
            "with an approved origin remote"
        )
    return resolved, suitable


def quote_bat(value: Path | str) -> str:
    return str(value).replace('"', '""')


def quote_sh(value: Path | str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def launcher_text(root: Path, repo_root: Path, approved_prefixes: list[str], mode: str = MODE_UPDATE) -> str:
    """Generate the per-archive launcher. Calls archive_sync, which auto-detects the owner at
    run time (surviving org/repo renames). The mode verb is the archive's configured intent;
    --yes makes it non-interactive for unattended/scheduled runs. Owner is never baked in."""
    verb = "--sync" if mode == MODE_SYNC else "--update"
    if WINDOWS:
        prefix_args = " ".join(f'--approved-remote-prefix "{quote_bat(prefix)}"' for prefix in approved_prefixes)
        return f"""@echo off
setlocal
set "REPO_ROOT={quote_bat(repo_root)}"
set "ARCHIVE_ROOT={quote_bat(root)}"
cd /d "%REPO_ROOT%"
uv run python gitArchiveUpdater\\archive_sync.py --root "%ARCHIVE_ROOT%" {verb} --yes {prefix_args} %*
exit /b %ERRORLEVEL%
"""

    prefix_args = " ".join(f"--approved-remote-prefix {quote_sh(prefix)}" for prefix in approved_prefixes)
    return f"""#!/usr/bin/env sh
set -eu
REPO_ROOT={quote_sh(repo_root)}
ARCHIVE_ROOT={quote_sh(root)}
cd "$REPO_ROOT"
exec uv run python gitArchiveUpdater/archive_sync.py --root "$ARCHIVE_ROOT" {verb} --yes {prefix_args} "$@"
"""


def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {"version": 1, "installations": []}
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("version", 1)
    data.setdefault("installations", [])
    return data


def save_registry(data: dict[str, object]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def upsert_record(record: InstallRecord) -> None:
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)

    existing = None
    for index, item in enumerate(installations):
        if Path(item["root"]).resolve() == Path(record.root).resolve():
            existing = index
            break

    payload = asdict(record)
    if existing is None:
        installations.append(payload)
    else:
        payload["installed_at"] = installations[existing].get("installed_at", record.installed_at)
        installations[existing] = payload
    save_registry(data)


def install_launchers(
    root: Path,
    approved_prefixes: list[str],
    show_progress: bool = False,
    prevalidated_repos: list[str] | None = None,
    mode: str = MODE_UPDATE,
) -> InstallRecord:
    if prevalidated_repos is None:
        resolved, repos = validate_archive_root(root, approved_prefixes, show_progress=show_progress)
    else:
        resolved = root.resolve()
        repos = prevalidated_repos
    python_executable = Path(sys.executable).resolve()
    launcher_path = resolved / LAUNCHER_NAME

    if show_progress:
        print()
        print(f"Writing archive launcher ({mode}): {launcher_path}")

    launcher_path.write_text(
        launcher_text(resolved, REPO_ROOT, approved_prefixes, mode=mode),
        encoding="utf-8",
        newline="\r\n" if WINDOWS else "\n",
    )

    stamp = now_stamp()
    record = InstallRecord(
        root=str(resolved),
        installed_at=stamp,
        updated_at=stamp,
        git_spec_ops_dir=str(REPO_ROOT),
        python_executable=str(python_executable),
        runner=f"uv run python gitArchiveUpdater/archive_sync.py ({mode})",
        launcher=str(launcher_path),
        launcher_type="bat" if WINDOWS else "sh",
        repo_count=len(repos),
        approved_remote_prefixes=approved_prefixes,
        mode=mode,
    )
    upsert_record(record)
    if show_progress:
        print(f"Registry updated: {REGISTRY_PATH}")
        print(f"Install complete: {len(repos)} suitable repo(s) registered.")
    log_event(f"installed archive root={resolved} launcher={launcher_path} repos={len(repos)}")
    return record


def forget_installation(root: Path) -> bool:
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)
    resolved = root.resolve()
    kept = [item for item in installations if Path(item["root"]).resolve() != resolved]
    if len(kept) == len(installations):
        return False
    data["installations"] = kept
    save_registry(data)
    log_event(f"forgot archive root={resolved}")
    return True


def installation_status(item: dict) -> dict[str, object]:
    root = Path(item["root"])
    launcher = Path(item.get("launcher") or item.get("bat_launcher") or item.get("powershell_launcher", ""))
    report_dir = root / DEFAULT_REPORT_DIR
    reports = sorted(report_dir.glob("archive-update-*.json")) if report_dir.exists() else []
    latest_report = reports[-1] if reports else None
    return {
        "root": str(root),
        "root_exists": root.exists() and root.is_dir(),
        "launcher_exists": launcher.exists(),
        "launcher": str(launcher),
        "launcher_type": item.get("launcher_type", "unknown"),
        "repo_count_at_install": item.get("repo_count", 0),
        "last_run_at": item.get("last_run_at"),
        "last_run_result": item.get("last_run_result"),
        "last_run_elapsed_seconds": item.get("last_run_elapsed_seconds"),
        "last_report": item.get("last_report"),
        "latest_report": str(latest_report) if latest_report else None,
        "latest_report_at": datetime.fromtimestamp(latest_report.stat().st_mtime).isoformat(timespec="seconds")
        if latest_report
        else None,
        "installed_at": item.get("installed_at"),
        "updated_at": item.get("updated_at"),
    }


def print_registry(show_status: bool) -> None:
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)
    print(f"{APP_NAME} v{VERSION}")
    print(f"Registry: {REGISTRY_PATH}")
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
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)
    print("=" * 60)
    print(f"{APP_NAME} v{VERSION}")
    print("=" * 60)
    print(f"Registry: {REGISTRY_PATH}")
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


def updater_command(item: dict, scan_only: bool, force_sync: bool = False) -> list[str]:
    root = Path(item["root"])
    command = [sys.executable, str(TOOL_DIR / "archive_sync.py"), "--root", str(root)]
    for prefix in item.get("approved_remote_prefixes") or DEFAULT_APPROVED_REMOTE_PREFIXES:
        command += ["--approved-remote-prefix", prefix]
    if scan_only:
        return command  # no verb -> archive_sync reports only
    # Each archive runs its configured mode; force_sync promotes all to sync for this run.
    mode = MODE_SYNC if (force_sync or item.get("mode") == MODE_SYNC) else MODE_UPDATE
    command += ["--sync" if mode == MODE_SYNC else "--update", "--yes"]
    return command


def refresh_all(scan_only: bool, force_sync: bool = False) -> int:
    started_all = time.perf_counter()
    data = load_registry()
    installations = data["installations"]
    assert isinstance(installations, list)
    if not installations:
        print("No managed archives to refresh.")
        return 0

    failures = 0
    refreshed = 0
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

        proc = subprocess.run(updater_command(item, scan_only, force_sync), cwd=REPO_ROOT, text=True)
        elapsed = round(time.perf_counter() - started, 3)
        status = "ok" if proc.returncode == 0 else f"failed: exit {proc.returncode}"
        details = installation_status(item)
        item["last_run_at"] = now_stamp()
        item["last_run_result"] = status
        item["last_run_elapsed_seconds"] = elapsed
        item["last_report"] = details.get("latest_report")
        item["last_report_at"] = details.get("latest_report_at")
        if proc.returncode != 0:
            failures += 1
        else:
            refreshed += 1
        if details.get("latest_report"):
            latest_reports.append(details["latest_report"])
        print(f"Archive refresh result: {status} ({elapsed:.3f}s)")
        log_event(f"refresh result root={root} status={status} elapsed={elapsed}s report={details.get('latest_report') or 'none'}")
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
    log_event(f"refresh-all complete mode={mode} succeeded={refreshed} failed={failures} elapsed={elapsed_all}s")
    return 1 if failures else 0


def refresh_all_script_text() -> str:
    if WINDOWS:
        return f"""@echo off
setlocal
cd /d "{quote_bat(REPO_ROOT)}"
uv run python gitArchiveUpdater\\archive_manager.py --refresh-all
exit /b %ERRORLEVEL%
"""
    return f"""#!/usr/bin/env sh
set -eu
cd {quote_sh(REPO_ROOT)}
exec uv run python gitArchiveUpdater/archive_manager.py --refresh-all "$@"
"""


def write_refresh_all_script() -> Path:
    REFRESH_ALL_SCRIPT.write_text(
        refresh_all_script_text(),
        encoding="utf-8",
        newline="\r\n" if WINDOWS else "\n",
    )
    log_event(f"wrote refresh-all script path={REFRESH_ALL_SCRIPT}")
    return REFRESH_ALL_SCRIPT


def install_monthly_task(task_name: str, day: int, time_of_day: str) -> int:
    if not WINDOWS:
        print("Automatic task creation is currently implemented for Windows Task Scheduler only.")
        print(f"Use this script with cron instead: {write_refresh_all_script()}")
        return 2

    script = write_refresh_all_script()
    command = [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        str(script),
        "/SC",
        "MONTHLY",
        "/D",
        str(day),
        "/ST",
        time_of_day,
        "/F",
    ]
    proc = subprocess.run(command, text=True)
    if proc.returncode == 0:
        log_event(f"scheduled monthly task name={task_name} day={day} time={time_of_day} script={script}")
    else:
        log_event(f"failed scheduling monthly task name={task_name} exit={proc.returncode}")
    return proc.returncode


def task_status(task_name: str) -> int:
    if not WINDOWS:
        print("Scheduled task status is implemented for Windows Task Scheduler only.")
        return 2
    proc = subprocess.run(["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"], text=True)
    return proc.returncode


def remove_task(task_name: str) -> int:
    if not WINDOWS:
        print("Scheduled task removal is implemented for Windows Task Scheduler only.")
        return 2
    proc = subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], text=True)
    if proc.returncode == 0:
        log_event(f"removed scheduled task name={task_name}")
    else:
        log_event(f"failed removing scheduled task name={task_name} exit={proc.returncode}")
    return proc.returncode


def choose_folder_dialog() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Choose archive folder to manage")
    root.destroy()
    return Path(folder) if folder else None


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
            path_text = prompt_input("Archive folder path (blank opens picker): ")
            if path_text:
                target = Path(path_text)
            else:
                target = choose_folder_dialog()
            if not target:
                print("No archive folder selected.")
                print()
                continue
            target = target.resolve()
            if not target.is_dir():
                print(f"Not a directory: {target}")
                print()
                continue

            # DETECT + PLAN: scan local + (if a provider matches) the authoritative remote set.
            print(f"Scanning {target} ...")
            result = detect_plan(target, approved_prefixes)
            render_plan(result)
            issues = list(result.errors)
            plan = result.plan

            # DECIDE + EXECUTE, bulk, human in the middle. Nothing applied without an explicit yes.
            if plan.to_clone and prompt_input(f"Clone {len(plan.to_clone)} missing repo(s) now? [y/N]: ").lower() in ("y", "yes"):
                apply_clone(target, plan, issues)
            stale = [it for it in plan.to_reconcile if it.origin_stale]
            if stale and prompt_input(f"Rewrite {len(stale)} stale origin URL(s)? [y/N]: ").lower() in ("y", "yes"):
                apply_reconcile_origins(target, plan, issues)
            drift = [it for it in plan.to_reconcile if it.folder_mismatch]
            if drift and prompt_input(f"Rename {len(drift)} folder(s) to match upstream? [y/N]: ").lower() in ("y", "yes"):
                apply_rename_folders(target, plan, issues)
            if plan.to_pull and prompt_input(f"Fast-forward {len(plan.to_pull)} repo(s) now? [y/N]: ").lower() in ("y", "yes"):
                apply_pull(target, plan, issues)

            print()
            review(issues)
            print()

            # CONFIGURE: pick the verb future (and scheduled) runs of this archive will use.
            is_org = result.provider_name is not None
            mode = MODE_UPDATE
            if is_org:
                ans = prompt_input("Mode for automated runs - [u]pdate-only (safe) or [s]ync (auto-clone new)? [U/s]: ").lower()
                mode = MODE_SYNC if ans in ("s", "sync") else MODE_UPDATE

            try:
                record = install_launchers(target, approved_prefixes, show_progress=True, mode=mode)
            except (ValueError, OSError) as exc:
                print(f"Error: {exc}")
                print()
                continue
            print(f"Installed archive launcher for {record.root}")
            print(f"  Launcher: {record.launcher}  (mode: {record.mode})")
            print(f"  Registry: {REGISTRY_PATH}")
            print()
            continue

        if choice == "2":
            refresh_all(scan_only=True)
            print()
            continue

        if choice == "3":
            confirm = prompt_input('Type "YES" to refresh all managed archives: ')
            if confirm == "YES":
                # Each archive runs its own configured mode. This promotes ALL of them to sync.
                force_sync = prompt_input(
                    "Force SYNC (clone missing) for EVERY archive, overriding per-archive mode? [y/N]: "
                ).strip().lower() in ("y", "yes")
                refresh_all(scan_only=False, force_sync=force_sync)
            else:
                print("Skipped.")
            print()
            continue

        if choice == "4":
            print_registry(show_status=True)
            print()
            prompt_input("Press ENTER to continue...")
            print()
            continue

        if choice == "5":
            path = write_refresh_all_script()
            print(f"Wrote refresh-all script: {path}")
            print()
            continue

        if choice == "6":
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
            print()
            continue

        if choice == "7":
            task_name = prompt_input(f"Task name [{DEFAULT_TASK_NAME}]: ") or DEFAULT_TASK_NAME
            code = task_status(task_name)
            if code != 0:
                print(f"Scheduled task query failed with exit {code}.")
            print()
            continue

        if choice == "8":
            task_name = prompt_input(f"Task name [{DEFAULT_TASK_NAME}]: ") or DEFAULT_TASK_NAME
            confirm = prompt_input(f'Type "YES" to remove scheduled task "{task_name}": ')
            if confirm == "YES":
                code = remove_task(task_name)
                print("Scheduled task removed." if code == 0 else f"Scheduled task removal failed with exit {code}.")
            else:
                print("Skipped.")
            print()
            continue

        if choice in {"q", "quit", "exit"}:
            return 0

        print("Unknown choice.")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and track ArchiveUpdater launchers.")
    parser.add_argument("--install", type=Path, help="Archive folder where a launcher should be created.")
    parser.add_argument("--mode", choices=VALID_MODES, default=MODE_UPDATE,
                        help="With --install: launcher verb for automated runs. 'update' (safe) or 'sync' (auto-clone).")
    parser.add_argument("--list", action="store_true", help="List registered launcher installations.")
    parser.add_argument("--status", action="store_true", help="List installations and verify paths still exist.")
    parser.add_argument("--forget", type=Path, help="Remove one archive folder from the registry.")
    parser.add_argument("--refresh-all", action="store_true", help="Run archive sync for every managed archive.")
    parser.add_argument("--scan-only", action="store_true", help="Use scan-only mode with --refresh-all.")
    parser.add_argument("--force-sync", action="store_true", help="Promote every archive to sync for this --refresh-all run.")
    parser.add_argument("--write-refresh-all-script", action="store_true", help="Write a script that refreshes all managed archives.")
    parser.add_argument("--install-monthly-task", action="store_true", help="Create/update a monthly Windows scheduled task.")
    parser.add_argument("--task-status", action="store_true", help="Show the Windows scheduled task status.")
    parser.add_argument("--remove-task", action="store_true", help="Remove the Windows scheduled task.")
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME, help="Scheduled task name.")
    parser.add_argument("--task-day", type=int, default=1, help="Day of month for --install-monthly-task.")
    parser.add_argument("--task-time", default="09:00", help="Start time for --install-monthly-task in HH:MM.")
    parser.add_argument(
        "--approved-remote-prefix",
        action="append",
        help="Allowed origin prefix. May be passed more than once. Defaults to https://github.com/.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    approved_prefixes = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES

    try:
        if args.refresh_all:
            return refresh_all(scan_only=args.scan_only, force_sync=args.force_sync)

        if args.write_refresh_all_script:
            path = write_refresh_all_script()
            print(f"Wrote refresh-all script: {path}")
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
            print("Removed from registry." if removed else "No matching registry entry found.")
            return 0 if removed else 1

        if not args.install:
            return interactive_menu(approved_prefixes)

        target = args.install
        if not target:
            print("No archive folder selected.")
            return 1

        record = install_launchers(target, approved_prefixes, show_progress=True, mode=args.mode)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error writing launcher or registry: {exc}", file=sys.stderr)
        return 3

    print(f"Installed archive launcher for {record.root}  (mode: {record.mode})")
    print(f"  Launcher: {record.launcher}")
    print(f"  Registry: {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




