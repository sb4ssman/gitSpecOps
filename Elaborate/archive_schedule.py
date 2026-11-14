"""Run every registered archive's refresh on a monthly schedule.

Why:          archives only stay current if their refresh runs on its own.
Reads:        registered archives; this user's scheduled tasks.
May change:   a refresh-all launcher and this user's scheduled task, only when asked.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Elaborate: other machines, or over time.
Status:       working

    gitso archive schedule --write-refresh-all-script
    gitso archive schedule --install-monthly-task --task-day 1 --task-time 09:00
    gitso archive schedule --task-status
    gitso archive schedule --remove-task

Only explicit actions run, each at once (like a setting). Generated launchers run archive
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
from Basic import _cli
from Basic._console import enable_unicode_output
from Special._runtime.files import checked_path
from Special._archive.manager import REPO_ROOT, log_event
from Special._archive.registry import load_registry, registry_path

EFFECT = "local"
REFRESH_ALL_LAUNCHER = "refresh_managed_archives"
DEFAULT_TASK_NAME = "gitSpecOps Archive Refresh"
MANAGE_SCRIPT = "Special/archive.py"


def write_refresh_all_script(*, home=None) -> Path:
    """Write only a requested future launcher, outside the source checkout."""
    home = checked_path(registry_path(home).parent)
    data = load_registry(home=home)
    data.verify()
    home.mkdir(parents=True, exist_ok=True)
    path = launcher.write_launcher(home, REFRESH_ALL_LAUNCHER, REPO_ROOT, MANAGE_SCRIPT,
                                   ["refresh", "--settings-home", str(home)])
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
    parser = _cli.parser("archive schedule", "Run every registered archive's refresh on a monthly schedule.")
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
    command = "archive schedule"
    try:
        if args.write_refresh_all_script:
            path = write_refresh_all_script(home=args.settings_home)
            return _cli.report(args, command, ok=True, page="Schedule archives", rows=[("Script", path)],
                               message="Wrote the refresh-all script.", script=str(path))
        if args.install_monthly_task:
            code = install_monthly_task(args.task_name, args.task_day, args.task_time, home=args.settings_home)
            return _cli.report(args, command, ok=code == 0, page="Schedule archives",
                               rows=[("Task", args.task_name), ("When", f"day {args.task_day}, {args.task_time}")],
                               message="Scheduled." if code == 0 else "The task was not created.",
                               task=args.task_name, day=args.task_day, time=args.task_time) or code
        if args.task_status:
            code = task_status(args.task_name)
            return _cli.report(args, command, ok=code == 0, page="Schedule archives", rows=[("Task", args.task_name)],
                               message="Scheduled." if code == 0 else "Not scheduled.",
                               task=args.task_name, scheduled=code == 0)
        code = remove_task(args.task_name, home=args.settings_home)
        return _cli.report(args, command, ok=code == 0, page="Schedule archives", rows=[("Task", args.task_name)],
                           message="Removed." if code == 0 else "The task was not removed.", task=args.task_name) or code
    except (ValueError, OSError):
        return _cli.fail(args, command, "Scheduling did not finish; check for a partial launcher or task.")


if __name__ == "__main__":
    raise SystemExit(main())
