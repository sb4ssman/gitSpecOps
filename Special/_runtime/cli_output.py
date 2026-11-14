"""The shared report and log switches. Parsing never reads settings or creates folders.

What a command prints follows the terminal (`Basic/_cli.py`): a screen for a person, JSON for
a program. These switches only decide whether the run's report is also saved as a JSON file, and
whether a counts-only log line is written (how many repositories were checked, updated, skipped;
never their names). `output_overrides` returns only the choices made explicitly, with paths taken
relative to the current folder, so a linked destination stays detectable by the runner.
"""
import argparse
from pathlib import Path

from Special._settings import SettingsError, _absolute


def add_output_options(parser):
    """Add --save-report / --report-dir and --log / --log-dir."""
    parser.add_argument("--save-report", action=argparse.BooleanOptionalAction, default=None,
                        help="also save this run's report as a JSON file (default: the saved choice, off)")
    parser.add_argument("--report-dir", type=Path, help="folder for the saved report; implies --save-report")
    parser.add_argument("--log", action=argparse.BooleanOptionalAction, default=None,
                        help="write a counts-only log line for this run (default: the saved choice, on)")
    parser.add_argument("--log-dir", type=Path, help="folder for the log; implies --log")


def output_overrides(args):
    """Validate the explicit choices; a contradiction is refused, never guessed."""
    if args.save_report is False and args.report_dir is not None:
        raise SettingsError("a report folder conflicts with --no-save-report")
    if args.log is False and args.log_dir is not None:
        raise SettingsError("a log folder conflicts with --no-log")
    overrides = {}
    if args.save_report is not None or args.report_dir is not None:
        overrides.setdefault("output", {})["save"] = args.save_report is not False
    if args.report_dir is not None:
        overrides.setdefault("output", {})["directory"] = str(_absolute(args.report_dir, Path.cwd()))
    if args.log is not None or args.log_dir is not None:
        overrides.setdefault("logging", {})["enabled"] = args.log is not False
    if args.log_dir is not None:
        overrides.setdefault("logging", {})["directory"] = str(_absolute(args.log_dir, Path.cwd()))
    return overrides
