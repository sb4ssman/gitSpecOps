"""Shared CLI channels. Parsing never reads settings or creates destinations.

add_output_options defines the switches. output_overrides returns only explicit choices,
with cwd-relative lexical paths so linked destinations remain detectable by the runner.
"""
import argparse
from pathlib import Path

from Special._settings import SettingsError, _absolute


def add_output_options(parser):
    """Add stdout/file/both, format and counts-only logging switches."""
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output-mode", choices=("stdout", "file", "both"))
    mode.add_argument("--no-report", action="store_true", help="Output to stdout only.")
    parser.add_argument("--output-dir", type=Path, help="Report directory; implies both unless mode is selected.")
    format = parser.add_mutually_exclusive_group()
    format.add_argument("--format", dest="output_format", choices=("text", "json"))
    format.add_argument("--json", dest="output_format", action="store_const", const="json", help="One structured operation result.")
    parser.add_argument("--log", action=argparse.BooleanOptionalAction, default=None, help="Enable/disable counts-only logging.")
    parser.add_argument("--log-dir", type=Path, help="Override counts-only log directory.")


def output_overrides(args):
    """Validate choices before resolution; invalid channels never fall back."""
    if args.output_dir is not None and (args.no_report or args.output_mode == "stdout"):
        raise SettingsError("report directory conflicts with stdout-only output")
    if args.log is False and args.log_dir is not None:
        raise SettingsError("log directory conflicts with disabled logging")
    overrides = {}
    if args.output_mode or args.no_report or args.output_dir is not None:
        overrides.setdefault("output", {})["mode"] = "stdout" if args.no_report else args.output_mode or "both"
    if args.output_format:
        overrides.setdefault("output", {})["format"] = args.output_format
    if args.output_dir is not None:
        overrides.setdefault("output", {})["directory"] = str(_absolute(args.output_dir, Path.cwd()))
    if args.log is not None or args.log_dir is not None:
        overrides.setdefault("logging", {})["enabled"] = args.log if args.log is not None else True
    if args.log_dir is not None:
        overrides.setdefault("logging", {})["directory"] = str(_absolute(args.log_dir, Path.cwd()))
    return overrides
