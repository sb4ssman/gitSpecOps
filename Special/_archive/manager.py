"""Local archive management shared by Special/archive_manager.py and scheduling above it.

Select/register archives, inspect status, forget registrations or refresh each using its saved
update/sync mode. Import main for CLI use, or the individual functions for trusted callers.
New launchers call --refresh with a fixed settings home; choices are read at run time.
Common profiles own archive choices; legacy-only profiles retain their registry. Registration
still creates a launcher. Refresh uses shared settings, structured results and optional sinks.
Scheduling belongs to Elaborate. Importing this module does not read or write user state.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from _os.current import launcher  # noqa: E402
from Basic._confirm import confirm_typed, prompt_input, prompt_yes_no  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._station import (  # noqa: E402
    ask, choose, is_console, menu_header, notice, option, row, run_header, say, section)
from Basic._discovery import list_child_dirs  # noqa: E402
from Basic._facts import is_repo_root  # noqa: E402
from Special._runtime.files import RuntimeIOError, checked_path, excluded, linked
from Special._runtime.cli_output import add_output_options, output_overrides
from Special._settings import SettingsError
from Special._settings.archives import _key
from Special._archive.registry import (  # noqa: E402
    InstallRecord,
    forget_installation,
    load_registry,
    registry_path,
    upsert_record,
)
from Special._archive.operation import run_refresh, render_result as render_refresh, error_message
from Special._archive.plan import (  # noqa: E402
    DEFAULT_APPROVED_REMOTE_PREFIXES,
    approved_remote,
    inspect_candidate,
)


EFFECT = "local"
APP_NAME = "Archive Manager"
VERSION = "0.4.0"
REPO_ROOT = Path(_ROOT)
MODE_UPDATE = "update"
MODE_SYNC = "sync"
VALID_MODES = (MODE_UPDATE, MODE_SYNC)
ARCHIVE_LAUNCHER = "update_archive"
MANAGER_SCRIPT = "Special/archive_manager.py"


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_path(home=None) -> Path:
    return registry_path(home).parent / "archive_manage.log"


def log_event(message: str, *, home=None) -> None:
    path = checked_path(log_path(home))
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
def _approved_prefixes(prefixes):
    """Refuse empty allowances rather than let the old engine widen them to defaults."""
    if not isinstance(prefixes, list) or not prefixes or any(
            not isinstance(value, str) or not value.strip() for value in prefixes):
        raise SettingsError("archive needs nonempty allowed remote prefixes; none were assumed")


def _guard_archive(data, root):
    """Enforce common exclusions before Git/report inspection; refuse unsupported partial scope."""
    preferences = getattr(data, "preferences", None)
    if preferences is None:
        return
    preferences.verify()
    try:
        checked_path(root)
        exclusions = preferences.resolved().values["scope"]["exclude_paths"]
        if excluded(root, exclusions, contains=True):
            raise SettingsError("managed archive conflicts with effective scope exclusions")
        if excluded(log_path(data.home), exclusions, contains=True):
            raise SettingsError("archive logging destination conflicts with effective scope exclusions")
        # The existing sync engine follows child-directory links. Refuse them before it runs.
        if root.is_dir() and any(linked(child) for child in root.iterdir()):
            raise SettingsError("managed archive contains linked entries; no repositories were inspected")
    except (RuntimeIOError, OSError):
        raise SettingsError("managed archive paths must be accessible and unlinked") from None


def install_launchers(root: Path, approved_prefixes: list[str] | None = None, show_progress: bool = False,
                      prevalidated_repos: list[str] | None = None,
                      mode: str | None = None, *, home=None) -> InstallRecord:
    """Explicit registration/launcher refresh; preserve unspecified saved choices and first receipt."""
    data = load_registry(home=home)
    selected = Path(os.path.abspath(root.expanduser()))
    existing = next((item for item in data["installations"] if _key(item["root"]) == _key(str(selected))), {})
    approved_prefixes = (existing.get("approved_remote_prefixes", DEFAULT_APPROVED_REMOTE_PREFIXES)
                         if approved_prefixes is None else approved_prefixes)
    mode = existing.get("mode", MODE_UPDATE) if mode is None else mode
    _approved_prefixes(approved_prefixes)
    if mode not in VALID_MODES:
        raise SettingsError("archive has an unsupported operation mode")
    _guard_archive(data, selected)
    if prevalidated_repos is None:
        resolved, repos = validate_archive_root(root, approved_prefixes, show_progress=show_progress)
    else:
        resolved, repos = root.resolve(), prevalidated_repos
    if show_progress:
        print()
        print(f"Writing archive launcher ({mode}) into: {resolved}")
    data.verify()
    try:
        written = launcher.write_launcher(resolved, ARCHIVE_LAUNCHER, REPO_ROOT, MANAGER_SCRIPT,
                                          ["--refresh", str(resolved), "--settings-home", str(data.home)])
    except OSError:
        raise SettingsError("launcher creation failed; some launcher files may exist; registration was not saved") from None
    launcher_type = "+".join(p.suffix.lstrip(".")
                             for p in launcher.launcher_files(resolved, ARCHIVE_LAUNCHER))
    stamp = now_stamp()
    record = InstallRecord(
        root=str(resolved),
        installed_at=stamp,
        updated_at=stamp,
        git_spec_ops_dir=str(REPO_ROOT),
        python_executable=str(Path(sys.executable).resolve()),
        runner=f"{MANAGER_SCRIPT} (saved mode)",
        launcher=str(written),
        launcher_type=launcher_type,
        repo_count=len(repos),
        approved_remote_prefixes=approved_prefixes,
        mode=mode,
    )
    try:
        upsert_record(record, expected=data)
    except (ValueError, OSError) as exc:
        raise SettingsError(f"archive launcher was written but registration did not finish: {exc}") from None
    if show_progress:
        print(f"Registry updated: {registry_path(data.home)}")
        print(f"Install complete: {len(repos)} suitable repo(s) registered.")
    try:
        log_event(f"installed archive root={resolved} launcher={written} repos={len(repos)}", home=data.home)
    except (ValueError, OSError):
        raise SettingsError("archive registration was saved but logging failed; review partial installation") from None
    return record


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------
def installation_status(item: dict) -> dict:
    """Current root/launcher facts plus historical receipt metadata; never guess a report file."""
    root = Path(item["root"])
    launcher_file = Path(item.get("launcher", ""))
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
        "latest_report": item.get("last_report"),
        "latest_report_at": item.get("last_report_at"),
        "installed_at": item.get("installed_at"),
        "updated_at": item.get("updated_at"),
    }


def print_registry(show_status: bool, *, home=None) -> None:
    data = load_registry(home=home)
    installations = data["installations"]
    print(f"{APP_NAME} v{VERSION}")
    print(f"Registry: {registry_path(home)}")
    print(f"Installations: {len(installations)}")
    for item in installations:
        if show_status:
            _guard_archive(data, Path(item["root"]))
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
            print(f"  launcher: {details.get('launcher') or 'not installed'}")
            print(f"  repos at install: {details.get('repo_count', 0)}")


def _archive_rows(item: dict, details: dict, *, full: bool = False) -> None:
    """One archive as station rows; `full` adds the paths and receipts."""
    row("Folder", "found" if details["root_exists"] else "missing", "success" if details["root_exists"] else "error")
    row("Mode", "sync: also downloads new repositories" if item.get("mode") == MODE_SYNC
        else "update: keeps the existing copies current")
    row("Repositories", f"{details['repo_count_at_install']} when it was added")
    row("Update shortcut", ("in the folder" if details["launcher_exists"] else "missing; add the folder again")
        + (f" ({details['launcher_type']})" if full else ""), "text" if details["launcher_exists"] else "warning")
    result = details.get("last_run_result")
    row("Last run", (details.get("last_run_at") or "never") + (f": {result}" if result else ""),
        "error" if result and result not in ("ok", "success", "completed") else "text")
    if full:
        row("Shortcut file", details.get("launcher") or "none")
        row("Added", details.get("installed_at") or "unknown")
        row("Took", f"{details.get('last_run_elapsed_seconds')} s" if details.get("last_run_elapsed_seconds") else "unknown")
        row("Latest report", details.get("latest_report") or "none")
    else:
        row("Latest report", details.get("latest_report_at") or "none")


def print_dashboard(*, home=None) -> None:
    """The archives menu screen's top: what is registered, each as rows."""
    data = load_registry(home=home)
    installations = data["installations"]
    menu_header("Archives")
    if not installations:
        notice("No archives yet", "An archive is a folder of full repository copies, kept current from "
               "GitHub. Add one with 1.")
        return
    notice(f"{len(installations)} archive{'s' if len(installations) != 1 else ''}",
           "Folders of full repository copies, kept current from GitHub.", "success")
    for index, item in enumerate(installations, start=1):
        _guard_archive(data, Path(item["root"]))
        section(f"{index}. {item['root']}")
        _archive_rows(item, installation_status(item))


def show_details(*, home=None) -> None:
    """Detection details for the archives: paths, receipts, the registry file."""
    data = load_registry(home=home)
    menu_header("Archive details")
    section("Records")
    row("Registry", str(registry_path(home)))
    row("Version", f"{APP_NAME} {VERSION}")
    for index, item in enumerate(data["installations"], start=1):
        _guard_archive(data, Path(item["root"]))
        section(f"{index}. {item['root']}")
        _archive_rows(item, installation_status(item), full=True)


# --------------------------------------------------------------------------------------
# Refreshing every managed archive, in-process
# --------------------------------------------------------------------------------------
def refresh_all(scan_only: bool, force_sync: bool = False, *, home=None,
                only_root: Path | None = None, overrides=None) -> int:
    """Present the shared headless result through selected CLI channels; at a console, as a
    station run screen (the caller draws its header)."""
    result = run_refresh(home=home, only_root=only_root, scan_only=scan_only, force_sync=force_sync, overrides=overrides)
    output = result.settings.values["output"] if result.settings is not None else None
    if is_console() and (output is None or (output["format"] != "json" and output["mode"] in ("stdout", "both"))):
        from Special._archive.console import show_refresh
        show_refresh(result, explain=error_message)
        return result.exit_code
    if result.settings is not None:
        output = result.settings.values["output"]
        if output["mode"] in ("stdout", "both"):
            print(render_refresh(result, output["format"]))
        else:
            for artifact in result.record()["artifacts"]:
                print(f"{artifact['kind']}: {artifact['path']}", file=sys.stderr)
    for error in result.errors:
        print("Error: " + error_message(error), file=sys.stderr)
    return result.exit_code


def refresh_archive(root: Path, scan_only: bool = False, force_sync: bool = False, *, home=None, overrides=None) -> int:
    """The generated-launcher and direct single-archive entry point over the same manager."""
    return refresh_all(scan_only, force_sync, home=home, only_root=root, overrides=overrides)

def choose_folder_dialog() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Choose archive folder to manage")
    root.destroy()
    return Path(folder) if folder else None


def _install_interactively(approved_prefixes: list[str], *, home=None) -> None:
    menu_header("Add an archive")
    notice("A folder of repository copies", "gitSpecOps registers it and puts an update shortcut in it. "
           "It reads the folder; it changes no repository until you run an update.")
    say()
    path_text = prompt_input("Folder path (Enter opens a folder picker): ")
    target = Path(path_text) if path_text else choose_folder_dialog()
    if not target:
        notice("Nothing added", "No folder was chosen.", "warning")
        return
    _guard_archive(load_registry(home=home), Path(os.path.abspath(target.expanduser())))
    target = target.resolve()
    if not target.is_dir():
        notice("Nothing added", f"Not a folder: {target}", "error")
        return

    # Registration never repairs origins/folders or runs a second operation pipeline.
    section("How it updates")
    option("1", "Update", "Keeps the copies already there current.")
    option("2", "Sync", "Also downloads repositories that are new on GitHub.")
    mode = MODE_SYNC if choose("12", "1") == "2" else MODE_UPDATE
    try:
        record = install_launchers(target, approved_prefixes, show_progress=True, mode=mode, home=home)
    except (ValueError, OSError) as exc:
        notice("Nothing added", str(exc), "error")
        return
    notice("Added", f"{record.root} is an archive ({record.mode}).", "success")
    row("Update shortcut", str(record.launcher))
    say()
    if prompt_yes_no("Update it now?", default=False):
        run_header("Updating an archive", f"{record.root}  |  mode: {record.mode}")
        refresh_archive(target, home=home)

def interactive_menu(approved_prefixes: list[str], *, home=None) -> int:
    if not sys.stdin.isatty():
        print("Select an explicit archive action; the interactive menu needs a terminal.", file=sys.stderr)
        return 2
    while True:
        print_dashboard(home=home)
        say()
        option("1", "Add an archive", "A folder of repository copies; it gets an update shortcut.")
        option("2", "Check every archive", "Reads what changed on GitHub; changes nothing.")
        option("3", "Update every archive", "Fetches, and fast-forwards each copy; never overwrites your work.")
        option("D", "Archive details")
        option("0", "Exit")
        choice = choose("123d0", "0")
        if choice == "0":
            return 0
        if choice == "1":
            _install_interactively(approved_prefixes, home=home)
        elif choice == "2":
            run_header("Checking archives", "reads every archive and GitHub; changes nothing")
            refresh_all(scan_only=True, home=home)
        elif choice == "3":
            menu_header("Update every archive")
            notice("Each archive updates in its own mode", "Copies are fast-forwarded only; work that is "
                   "only on this computer is never overwritten.")
            say()
            if not confirm_typed("YES", "Type YES to update every archive: "):
                notice("Cancelled", "Nothing was updated.", "warning")
            else:
                # Each archive runs its own configured mode. This promotes ALL of them to sync.
                force_sync = prompt_yes_no("Also download new repositories for every archive (sync), "
                                           "whatever its own mode?", default=False)
                run_header("Updating archives", "every registered archive"
                           + ("  |  sync: also downloads new repositories" if force_sync else ""))
                refresh_all(scan_only=False, force_sync=force_sync, home=home)
        elif choice == "d":
            show_details(home=home)
        say()
        ask("Press Enter to return:")


def refresh_overrides(args, parser=None):
    """Output choices are valid only for a selected refresh action."""
    selected = any((args.output_mode, args.no_report, args.output_dir is not None,
                    args.output_format, args.log is not None, args.log_dir is not None))
    try:
        if selected and not (args.refresh or args.refresh_all):
            raise SettingsError("refresh output/logging options require --refresh or --refresh-all")
        return output_overrides(args)
    except SettingsError as exc:
        if parser is not None:
            parser.error(str(exc))
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register archive folders, give each a launcher, "
                                                 "and refresh them together.")
    parser.add_argument("--settings-home", type=Path, help="Selected user-data profile; no migration or relocation.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", type=Path, help="Archive folder where a launcher should be created.")
    parser.add_argument("--mode", choices=VALID_MODES,
                        help="With --install: launcher verb for automated runs. 'update' (safe) or "
                             "'sync' (auto-clone). Omission preserves the saved choice, otherwise update.")
    actions.add_argument("--list", action="store_true", help="List registered archives.")
    actions.add_argument("--status", action="store_true", help="List archives and verify paths still exist.")
    actions.add_argument("--forget", type=Path, help="Remove a registration; retain common-profile receipts and launchers.")
    actions.add_argument("--refresh", type=Path, help="Run one registered archive using current saved choices.")
    actions.add_argument("--refresh-all", action="store_true", help="Run archive sync for every managed archive.")
    parser.add_argument("--scan-only", action="store_true", help="Use scan-only mode with --refresh/--refresh-all.")
    parser.add_argument("--force-sync", action="store_true",
                        help="Promote every archive to sync for this --refresh-all run.")
    parser.add_argument("--approved-remote-prefix", action="append",
                        help="Allowed origin prefix. Repeatable. Defaults to the common GitHub forms.")
    add_output_options(parser)
    args = parser.parse_args(argv)
    refresh_overrides(args, parser)
    if (args.scan_only or args.force_sync) and not (args.refresh_all or args.refresh):
        parser.error("--scan-only/--force-sync require --refresh or --refresh-all")
    if args.mode is not None and not args.install:
        parser.error("--mode requires --install; --refresh reads the saved mode")
    if args.approved_remote_prefix is not None and not args.install:
        parser.error("--approved-remote-prefix requires --install; --refresh reads saved allowances")
    return args


def main(argv: list[str] | None = None) -> int:
    enable_unicode_output()
    args = parse_args(argv)
    approved_prefixes = args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES
    try:
        if args.refresh:
            return refresh_archive(args.refresh, args.scan_only, args.force_sync, home=args.settings_home, overrides=refresh_overrides(args))
        if args.refresh_all:
            return refresh_all(scan_only=args.scan_only, force_sync=args.force_sync, home=args.settings_home, overrides=refresh_overrides(args))
        if args.list or args.status:
            print_registry(show_status=args.status, home=args.settings_home)
            return 0
        if args.forget:
            removed = forget_installation(args.forget, home=args.settings_home)
            if removed:
                log_event(f"forgot archive root={args.forget.resolve()}", home=args.settings_home)
            print("Removed from registry." if removed else "No matching registry entry found.")
            return 0 if removed else 1
        if not args.install:
            return interactive_menu(approved_prefixes, home=args.settings_home)
        record = install_launchers(args.install, args.approved_remote_prefix, show_progress=True,
                                  mode=args.mode, home=args.settings_home)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error writing launcher or registry: {exc}", file=sys.stderr)
        return 3

    print(f"Installed archive launcher for {record.root}  (mode: {record.mode})")
    print(f"  Launcher: {record.launcher}")
    print(f"  Registry: {registry_path(args.settings_home)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
