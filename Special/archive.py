"""Register folders of clones (archives) and refresh them, each in its saved mode.

Why:          archives you keep should refresh the way you chose for each, with one command.
Reads:        registered archives and their saved update or sync mode.
May change:   registrations and their launchers (planned first); the checkouts a refresh updates
              or clones.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso archive                                    (a menu, at a terminal)
    gitso archive add /path/to/archive --mode update
    gitso archive list
    gitso archive check --no-log                     (every archive, changing nothing)
    gitso archive refresh /path/to/archive

add and remove show their plan and act on approval: --apply PLAN_ID, or yes at a
terminal. remove forgets the registration only; the folder and its launcher stay. A refresh
runs each archive in its saved mode: registering it was the approval, so the launcher and the
monthly task (archive schedule) run unattended. check looks without changing anything.
--save-report/--report-dir also save the run's report as a JSON file; --log/--no-log choose the
counts-only log. Import run_refresh for programmatic use; it prints nothing.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._archive.manager import (
    now_stamp,
    log_path,
    log_event,
    scan_suitable_repos_with_progress,
    validate_archive_root,
    install_launchers,
    forget_installation,
    load_registry,
    registry_path,
    installation_status,
    print_registry,
    refresh_all,
    run_refresh,
    refresh_archive,
    choose_folder_dialog,
    interactive_menu,
    build_parser,
    menu_main,
    main,
    EFFECT,
    REPO_ROOT,
    MODE_UPDATE,
    MODE_SYNC,
    VALID_MODES,
    ARCHIVE_LAUNCHER,
)

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
