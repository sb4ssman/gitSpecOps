"""Schedule registered archive refreshes; local management lives in Special.

    python Elaborate/archive_manage.py --write-refresh-all-script
    python Elaborate/archive_manage.py --install-monthly-task --task-day 1 --task-time 09:00
    python Elaborate/archive_manage.py --task-status
    python Elaborate/archive_manage.py --remove-task

Only explicit actions run. Newly generated launchers invoke Special/archive_manager.py
--refresh-all at the selected profile. Scheduling never enables publication or repairs.
Importing writes nothing and does not inspect or alter installed tasks.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from _os.current import launcher, schedule
from Basic._console import enable_unicode_output
from Special._runtime.files import checked_path
from Special._archive.manager import REPO_ROOT, log_event
from Special._archive.registry import load_registry, registry_path

EFFECT = "local"
REFRESH_ALL_LAUNCHER = "refresh_managed_archives"
DEFAULT_TASK_NAME = "gitSpecOps Archive Refresh"
MANAGE_SCRIPT = "Special/archive_manager.py"


def write_refresh_all_script(*, home=None) -> Path:
    """Write only a requested future launcher, outside the source checkout."""
    home = checked_path(registry_path(home).parent)
    data = load_registry(home=home)
    data.verify()
    home.mkdir(parents=True, exist_ok=True)
    path = launcher.write_launcher(home, REFRESH_ALL_LAUNCHER, REPO_ROOT, MANAGE_SCRIPT,
                                   ["--refresh-all", "--settings-home", str(home)])
    log_event(f"wrote refresh-all script path={path}", home=home)
    return path


def install_monthly_task(task_name: str, day: int, time_of_day: str, *, home=None) -> int:
    """Explicit scheduling action; caller controls the task name and selected profile."""
    script = write_refresh_all_script(home=home)
    code = schedule.install_monthly(task_name, script, day, time_of_day)
    log_event(f"schedule monthly task name={task_name} day={day} time={time_of_day} "
              f"script={script} exit={code}", home=home)
    return code


def task_status(task_name: str) -> int:
    return schedule.status(task_name)


def remove_task(task_name: str, *, home=None) -> int:
    code = schedule.remove(task_name)
    log_event(f"remove scheduled task name={task_name} exit={code}", home=home)
    return code


def parse_args(argv=None):
    """Reject local management and invalid scheduling choices before any file writes."""
    parser = argparse.ArgumentParser(description="Schedule refreshes registered with Special/archive_manager.py.")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write-refresh-all-script", action="store_true")
    actions.add_argument("--install-monthly-task", action="store_true")
    actions.add_argument("--task-status", action="store_true")
    actions.add_argument("--remove-task", action="store_true")
    parser.add_argument("--settings-home", type=Path)
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    parser.add_argument("--task-day", type=int, default=1)
    parser.add_argument("--task-time", default="09:00")
    args = parser.parse_args(argv)
    if not args.task_name.strip():
        parser.error("task name must be nonempty")
    if not 1 <= args.task_day <= 31:
        parser.error("task day must be between 1 and 31")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", args.task_time):
        parser.error("task time must be HH:MM")
    return args


def main(argv=None):
    enable_unicode_output()
    args = parse_args(argv)
    try:
        if args.write_refresh_all_script:
            print(f"Wrote refresh-all script: {write_refresh_all_script(home=args.settings_home)}")
            return 0
        if args.install_monthly_task:
            return install_monthly_task(args.task_name, args.task_day, args.task_time, home=args.settings_home)
        if args.task_status:
            return task_status(args.task_name)
        return remove_task(args.task_name, home=args.settings_home)
    except (ValueError, OSError):
        print("Scheduling operation did not complete; inspect any partial launcher/task locally.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
