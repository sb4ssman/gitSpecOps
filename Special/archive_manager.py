"""Register local archive folders and refresh them using their saved update or sync mode.

    python Special/archive_manager.py --help
    python Special/archive_manager.py --install /path/to/archive --mode update
    python Special/archive_manager.py --list
    python Special/archive_manager.py --refresh-all --scan-only --json --no-report --no-log
    python Special/archive_manager.py --refresh /path/to/archive --settings-home /path/to/profile

--install creates a launcher that resolves saved choices at run time. --forget removes the
registration only; common-profile receipts and launchers remain for ownership review. Existing
common settings own choices; legacy-only profiles retain their registry without migration.
Use Elaborate/archive_manage.py for scheduling. Importing performs no operation.

Refresh calls run_refresh headlessly: saved update/sync mode per archive, one masked result,
optional aggregate report, shared counts-only logging. --output-mode/--output-dir/--json and
--log/--no-log/--log-dir override manager preferences. Reports default off; selected invalid
sinks fail without fallback. --scan-only leaves receipts unchanged. Action receipts contain
run status, not a guessed last report; actual report/log destinations are result artifacts.
Import run_refresh for programmatic use; it prints nothing and replaces no process streams.
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
    print_dashboard,
    refresh_all,
    run_refresh,
    refresh_archive,
    choose_folder_dialog,
    interactive_menu,
    parse_args,
    main,
    EFFECT,
    APP_NAME,
    VERSION,
    REPO_ROOT,
    MODE_UPDATE,
    MODE_SYNC,
    VALID_MODES,
    ARCHIVE_LAUNCHER,
)

if __name__ == "__main__":
    raise SystemExit(main())
