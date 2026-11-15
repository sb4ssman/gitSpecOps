"""Local archive management shared by Special/archive_manager.py and scheduling above it.

Select/register archives, inspect status, forget registrations or refresh each using its saved
update/sync mode. Import main for CLI use, or the individual functions for trusted callers.
New launchers call --refresh with a fixed settings home; choices are read at run time.
The settings profile owns archive choices. Registration
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
from Basic._console import enable_unicode_output  # noqa: E402
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
    print()
    print(f"  Looking at {len(child_dirs)} folder(s) inside it")
    if not child_dirs:
        print("    none")
        return suitable
    for index, path in enumerate(child_dirs, start=1):
        print(f"    [{index}/{len(child_dirs)}] {path.name} ... ", end="", flush=True)
        repo = inspect_candidate(path, approved_prefixes)
        if _suitable(repo, approved_prefixes):
            suitable.append(repo.name)
            print("suitable")
        elif repo.is_work_tree:
            print(repo.action.removeprefix("skip: "))
        else:
            print("not a repo")
    print(f"  {len(suitable)} repositories can be kept current here.")
    return suitable


def validate_archive_root(root: Path, approved_prefixes: list[str],
                          show_progress: bool = False) -> tuple[Path, list[str]]:
    resolved = root.resolve()
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


COMMAND = "archive-manager"


def registry_record(show_status: bool, *, home=None) -> dict:
    """Every registered archive, with its saved mode and (with status) what is true on disk now."""
    data = load_registry(home=home)
    archives = []
    for item in data["installations"]:
        if show_status:
            _guard_archive(data, Path(item["root"]))
        details = installation_status(item)
        entry = {"root": details["root"], "mode": item.get("mode", "update"),
                 "installed_at": details.get("installed_at"), "updated_at": details.get("updated_at"),
                 "repos_at_install": details["repo_count_at_install"],
                 "launcher": details.get("launcher") or None,
                 "last_run_at": details.get("last_run_at"), "last_run_result": details.get("last_run_result")}
        if show_status:
            entry.update(root_exists=details["root_exists"], launcher_exists=details["launcher_exists"],
                         launcher_type=details["launcher_type"],
                         last_run_elapsed_seconds=details.get("last_run_elapsed_seconds"),
                         latest_report=details.get("latest_report"))
        archives.append(entry)
    return {"registry": str(registry_path(home)), "archives": archives}


def _show_archives(record: dict, show_status: bool) -> None:
    from Basic._station import line, row, say, section
    from Basic._cli import shown
    if not record["archives"]:
        say()
        line("No archives registered yet.")
    for number, entry in enumerate(record["archives"], 1):
        section(f"{number}. {entry['root']}")
        row("Mode", "update existing clones" if entry["mode"] == "update" else "update and clone missing")
        row("Repositories", f"{entry['repos_at_install']} when registered")
        row("Last run", f"{shown(entry['last_run_at'])}  {shown(entry['last_run_result'])}")
        if show_status:
            row("Folder", "ok" if entry["root_exists"] else "missing", "success" if entry["root_exists"] else "error")
            row("Launcher", f"{'ok' if entry['launcher_exists'] else 'missing'} ({entry['launcher_type']})",
                "success" if entry["launcher_exists"] else "error")
            row("Latest report", shown(entry["latest_report"]))


def print_registry(show_status: bool, *, home=None, args=None) -> None:
    from Basic import _cli
    from Basic._station import banner
    record = registry_record(show_status, home=home)

    def screen():
        banner("Archives", f"registry: {record['registry']}")
        _show_archives(record, show_status)

    _cli.emit(args, _cli.document(COMMAND, **record), screen)


# --------------------------------------------------------------------------------------
# Refreshing registered archives. Registering a folder is the approval: the scheduled task
# runs this unattended, each archive in its own saved mode.
# --------------------------------------------------------------------------------------
def refresh_all(scan_only: bool, *, home=None, only_root: Path | None = None, overrides=None, args=None) -> int:
    from Basic import _cli
    result = run_refresh(home=home, only_root=only_root, scan_only=scan_only, overrides=overrides)
    errors = [error_message(error) for error in result.errors]
    record = _cli.document(COMMAND, result.exit_code == 0, **result.record())
    if errors:
        record["messages"] = errors

    def screen():
        from Basic._station import banner, line, notice, say
        banner("Archives  /  Check" if scan_only else "Archives  /  Refresh",
               str(only_root) if only_root else "every registered archive")
        say()
        for text in render_refresh(result, "text").splitlines():
            line(text)
        for text in errors:
            notice("Stopped", text, "error")

    _cli.emit(args, record, screen)
    return result.exit_code


def refresh_archive(root: Path, scan_only: bool = False, *, home=None, overrides=None, args=None) -> int:
    """The generated-launcher and direct single-archive entry point over the same manager."""
    return refresh_all(scan_only, home=home, only_root=root, overrides=overrides, args=args)


def choose_folder_dialog() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Choose a folder of clones")
    root.destroy()
    return Path(folder) if folder else None


# --------------------------------------------------------------------------------------
# Registering and forgetting: plan first, apply on approval.
# --------------------------------------------------------------------------------------
def registration_plan(root: Path, approved_prefixes, mode, *, home=None, show_progress=False) -> dict:
    """What registering `root` would do. Reads the folder; changes nothing."""
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
    resolved, repos = validate_archive_root(root, approved_prefixes, show_progress=show_progress)
    return {"action": "register", "root": str(resolved), "mode": mode, "already_registered": bool(existing),
            "allowed_remotes": list(approved_prefixes), "repositories": sorted(repos),
            "launcher": str(resolved / ARCHIVE_LAUNCHER)}


def _show_plan(plan: dict) -> None:
    from Basic._station import row, say, section
    section("Register this folder of clones" if plan["action"] == "register" else "Forget this archive")
    say()
    row("Folder", plan["root"])
    if plan["action"] == "register":
        row("Mode", "update existing clones" if plan["mode"] == "update" else "update and clone missing ones")
        names = plan["repositories"]
        row("Repositories", f"{len(names)}: " + ", ".join(names[:8]) + (f", and {len(names) - 8} more" if len(names) > 8 else ""))
        row("Launcher", plan["launcher"] + " (.bat/.ps1 or .sh)")
        row("Already registered", "yes, its choices are updated" if plan["already_registered"] else "no")
    else:
        row("Kept", "the folder, its clones and its launcher; only the registration goes")


def register(args, argv) -> int:
    from Basic import _cli
    screen = not _cli.machine(args)
    if screen:
        from Basic._station import banner
        banner("Archives  /  Register", str(args.install))
    try:
        plan = registration_plan(args.install, args.allowed_remote, args.mode, home=args.settings_home,
                                 show_progress=screen)
    except (ValueError, OSError) as exc:
        return _cli.fail(args, COMMAND, f"{exc}.")
    approval = _cli.Approval(args, COMMAND, argv)
    if not approval.decide(plan, lambda: _show_plan(plan), question="Register this folder?"):
        return approval.code
    record = install_launchers(args.install, args.allowed_remote, prevalidated_repos=plan["repositories"],
                               mode=args.mode, home=args.settings_home)
    return _cli.report(args, COMMAND, ok=True, page="Archives  /  Registered", context=(record.root,),
                       rows=[("Mode", record.mode), ("Launcher", record.launcher),
                             ("Repositories", record.repo_count)],
                       message="Registered. Its launcher refreshes it in this mode; "
                               "schedule-archives can run them monthly.",
                       root=record.root, mode=record.mode, launcher=record.launcher, repositories=record.repo_count)


def forget(args, argv) -> int:
    from Basic import _cli
    data = load_registry(home=args.settings_home)
    key = _key(os.path.realpath(args.forget.expanduser()))
    if not any(_key(item["root"]) == key for item in data["installations"]):
        return _cli.fail(args, COMMAND, "That folder is not a registered archive.", _cli.FAILED)
    plan = {"action": "forget", "root": str(Path(os.path.realpath(args.forget.expanduser())))}
    approval = _cli.Approval(args, COMMAND, argv)
    if not _cli.machine(args):
        from Basic._station import banner
        banner("Archives  /  Forget", plan["root"])
    if not approval.decide(plan, lambda: _show_plan(plan), question="Forget this archive?"):
        return approval.code
    removed = forget_installation(args.forget, home=args.settings_home)
    if removed:
        log_event(f"forgot archive root={plan['root']}", home=args.settings_home)
    return _cli.report(args, COMMAND, ok=removed, page="Archives  /  Forgotten", context=(plan["root"],),
                       message="Forgotten; the folder and its launcher are untouched." if removed
                       else "No matching registration was found.", root=plan["root"])


# --------------------------------------------------------------------------------------
# The menu, for a person at a terminal.
# --------------------------------------------------------------------------------------
def _register_interactively(approved_prefixes, *, home=None) -> None:
    from Basic import _cli
    from Basic._station import ask, choose, notice, option, say
    say()
    text = ask("Folder of clones (blank opens a folder picker):")
    target = Path(text) if text else choose_folder_dialog()
    if not target:
        notice("Nothing chosen", "No folder was registered.")
        return
    say()
    option("1", "Update the clones already there", "Fast-forward only; never clones, merges or deletes.")
    option("2", "Also clone repositories that are missing", "Compared with the GitHub owner of the clones.")
    mode = MODE_SYNC if choose("12", "1") == "2" else MODE_UPDATE
    try:
        plan = registration_plan(target, approved_prefixes, mode, home=home, show_progress=True)
    except (ValueError, OSError) as exc:
        notice("Not registered", f"{exc}.", "error")
        return
    _show_plan(plan)
    if not _cli.confirm("Register this folder?"):
        notice("Not registered", "Nothing was changed.")
        return
    try:
        record = install_launchers(target, approved_prefixes, prevalidated_repos=plan["repositories"],
                                   mode=mode, home=home)
    except (ValueError, OSError) as exc:
        notice("Not registered", f"{exc}.", "error")
        return
    notice("Registered", f"{record.root} ({record.mode}). Its launcher: {record.launcher}", "success")
    say()
    if _cli.confirm("Refresh it now?"):
        refresh_archive(target, home=home)


def interactive_menu(approved_prefixes, *, home=None) -> int:
    from Basic import _cli
    from Basic._station import ask, banner, choose, notice, option, say
    if not _cli.interactive():
        print("Choose an action (see --help); the menu needs a terminal.", file=sys.stderr)
        return _cli.USAGE
    while True:
        record = registry_record(False, home=home)
        banner("Archives", tagline=True)
        count = len(record["archives"])
        notice(f"{count} folder{'s' if count != 1 else ''} of clones registered",
               "Each is kept current in its own mode by its launcher, or by schedule-archives.")
        _show_archives(record, False)
        say()
        option("1", "Register a folder of clones", "Choose the folder and its mode; you review before anything is saved.")
        option("2", "Check every archive now", "Reads only; nothing is pulled or cloned.")
        option("3", "Refresh every archive now", "Each in its saved mode.")
        option("D", "Details", "Folders, launchers, last runs and reports.")
        option("0", "Exit")
        answer = choose("123d0", "0")
        if answer == "1":
            _register_interactively(approved_prefixes, home=home)
        elif answer == "2":
            refresh_all(scan_only=True, home=home)
        elif answer == "3":
            if _cli.confirm("Refresh every registered archive now?"):
                refresh_all(scan_only=False, home=home)
        elif answer == "d":
            print_registry(show_status=True, home=home)
        else:
            return _cli.OK
        say()
        ask("Press Enter to go back to the archives menu.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from Basic import _cli
    parser = _cli.parser(COMMAND, "Register folders of clones, give each a launcher, and refresh them.")
    parser.add_argument("--settings-home", type=Path, help="use the settings in this folder instead")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", type=Path, metavar="FOLDER",
                         help="register a folder of clones (shows the plan first)")
    parser.add_argument("--mode", choices=VALID_MODES,
                        help="with --install: update (existing clones only) or sync (also clone missing ones); "
                             "default: the saved choice, else update")
    actions.add_argument("--list", action="store_true", help="list registered archives")
    actions.add_argument("--status", action="store_true", help="list them and check their folders and launchers")
    actions.add_argument("--forget", type=Path, metavar="FOLDER",
                         help="remove a registration (shows the plan first); keeps every file")
    actions.add_argument("--refresh", type=Path, metavar="FOLDER", help="refresh one registered archive in its saved mode")
    actions.add_argument("--refresh-all", action="store_true", help="refresh every registered archive in its saved mode")
    parser.add_argument("--scan-only", action="store_true",
                        help="with --refresh/--refresh-all: check without changing anything")
    parser.add_argument("--allowed-remote", action="append",
                        help="with --install: only origins starting with this; repeatable (default: GitHub)")
    add_output_options(parser)
    _cli.add_apply(parser)
    args = parser.parse_args(argv)
    refresh_overrides(args, parser)
    if args.scan_only and not (args.refresh_all or args.refresh):
        parser.error("--scan-only requires --refresh or --refresh-all")
    if args.mode is not None and not args.install:
        parser.error("--mode requires --install; --refresh reads the saved mode")
    if args.allowed_remote is not None and not args.install:
        parser.error("--allowed-remote requires --install; --refresh reads the saved choice")
    if args.apply is not None and not (args.install or args.forget):
        parser.error("--apply goes with --install or --forget; a refresh runs the registered choice")
    return args


def refresh_overrides(args, parser=None):
    """Report and log choices go only with a refresh."""
    selected = any((args.save_report is not None, args.report_dir is not None,
                    args.log is not None, args.log_dir is not None))
    try:
        if selected and not (args.refresh or args.refresh_all):
            raise SettingsError("report and log options go with --refresh or --refresh-all")
        return output_overrides(args)
    except SettingsError as exc:
        if parser is not None:
            parser.error(str(exc))
        raise


def main(argv: list[str] | None = None) -> int:
    from Basic import _cli
    enable_unicode_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    try:
        if args.refresh:
            return refresh_archive(args.refresh, args.scan_only, home=args.settings_home,
                                   overrides=refresh_overrides(args), args=args)
        if args.refresh_all:
            return refresh_all(scan_only=args.scan_only, home=args.settings_home,
                               overrides=refresh_overrides(args), args=args)
        if args.list or args.status:
            print_registry(show_status=args.status, home=args.settings_home, args=args)
            return _cli.OK
        if args.forget:
            return forget(args, argv)
        if args.install:
            return register(args, argv)
        return interactive_menu(DEFAULT_APPROVED_REMOTE_PREFIXES, home=args.settings_home)
    except (ValueError, OSError) as exc:
        return _cli.fail(args, COMMAND, f"{exc}.")


if __name__ == "__main__":
    raise SystemExit(main())
