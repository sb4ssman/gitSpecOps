"""Archive Updater CLI over run_update. Help does not read settings or configure sinks.

Explicit flags override component/common preferences;
--no-report means stdout only, while --no-log separately disables operational logging.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from Basic._console import enable_unicode_output
from Basic._run import DEFAULT_GIT_TIMEOUT_SECONDS, set_git_timeout
from Special._archive.update_operation import UpdateRequest, explain_error, render_result, run_update
from Special._archive.plan import DEFAULT_APPROVED_REMOTE_PREFIXES
from Special._settings import SettingsError, resolve_settings, _absolute


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update eligible existing checkouts using optional local preferences.")
    parser.add_argument("--root", type=Path, action="append", help="Override saved roots; otherwise saved roots or cwd.")
    parser.add_argument("--exclude-path", type=Path, action="append", help="Add a hard scope exclusion; repeatable.")
    parser.add_argument("--settings-home", type=Path, help="Select a user-data home without migrating it.")
    parser.add_argument("--scan-only", action="store_true", help="Inspect without pulling; requested logs/reports still apply.")
    parser.add_argument("--output-dir", type=Path, help="Explicit report directory; implies both output unless mode is set.")
    parser.add_argument("--default-output-dir", type=Path, help="Report directory relative to the single effective root.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output-mode", choices=("stdout", "file", "both"))
    mode.add_argument("--no-report", action="store_true", help="Override saved file output with stdout only.")
    format = parser.add_mutually_exclusive_group()
    format.add_argument("--format", dest="output_format", choices=("text", "json"))
    format.add_argument("--json", dest="output_format", action="store_const", const="json", help="JSON for the selected output channels.")
    parser.add_argument("--log", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable/disable configured operational logging (default preference: enabled).")
    parser.add_argument("--log-dir", type=Path, help="Override operational log directory.")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))
    parser.add_argument("--approved-remote-prefix", action="append", help="Allowed origin prefix; repeatable.")
    parser.add_argument("--show-remote-urls", action="store_true", help="Show origins while still redacting credentials.")
    parser.add_argument("--git-timeout", type=int, default=DEFAULT_GIT_TIMEOUT_SECONDS)
    return parser


def operation_settings(args):
    """Resolve once; explicit CLI paths are cwd-relative, saved paths remain home-relative."""
    if args.git_timeout < 1:
        raise SettingsError("git timeout must be positive")
    if args.output_dir is not None and args.default_output_dir is not None:
        raise SettingsError("choose one report directory option")
    explicit_report = args.output_dir is not None or args.default_output_dir is not None
    if explicit_report and (args.no_report or args.output_mode == "stdout"):
        raise SettingsError("report directory conflicts with stdout-only output")
    if args.log is False and args.log_dir is not None:
        raise SettingsError("log directory conflicts with disabled logging")
    overrides = {}
    if args.root is not None:
        overrides.setdefault("scope", {})["roots"] = [str(_absolute(path, Path.cwd())) for path in args.root]
    if args.exclude_path is not None:
        overrides.setdefault("scope", {})["exclude_paths"] = [str(path.resolve()) for path in args.exclude_path]
    if args.no_report or args.output_mode is not None or explicit_report:
        overrides.setdefault("output", {})["mode"] = ("stdout" if args.no_report else args.output_mode or "both")
    if args.output_format is not None:
        overrides.setdefault("output", {})["format"] = args.output_format
    if args.output_dir is not None:
        overrides.setdefault("output", {})["directory"] = str(_absolute(args.output_dir, Path.cwd()))
    if args.log is not None or args.log_dir is not None:
        overrides.setdefault("logging", {})["enabled"] = args.log if args.log is not None else True
    if args.log_dir is not None:
        overrides.setdefault("logging", {})["directory"] = str(_absolute(args.log_dir, Path.cwd()))
    if args.log_level is not None:
        overrides.setdefault("logging", {})["level"] = args.log_level
    settings = resolve_settings("archive_update", home=args.settings_home, overrides=overrides)
    if args.default_output_dir is not None:
        roots = settings.values["scope"]["roots"] or [Path.cwd()]
        if len(roots) != 1:
            raise SettingsError("default output directory requires one effective root")
        settings.values["output"]["directory"] = _absolute(args.default_output_dir, roots[0])
        settings.sources["output.directory"] = ["explicit"]
    return settings


def main(argv=None) -> int:
    enable_unicode_output()
    args = build_parser().parse_args(argv)
    try:
        settings = operation_settings(args)
    except SettingsError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 2
    set_git_timeout(args.git_timeout)
    request = UpdateRequest(scan_only=args.scan_only,
                            approved_prefixes=tuple(args.approved_remote_prefix or DEFAULT_APPROVED_REMOTE_PREFIXES))
    result = run_update(settings, request, progress=lambda text: print(text, file=sys.stderr),
                        show_remote_urls=args.show_remote_urls)
    if settings.values["output"]["mode"] in ("stdout", "both"):
        print(render_result(result, settings.values["output"]["format"],
                            show_remote_urls=args.show_remote_urls))
    else:
        for artifact in result.record()["artifacts"]:
            print(f"{artifact['kind']}: {artifact['path']}", file=sys.stderr)
    for error in result.errors:
        print(f"Error: {explain_error(error)} Review the result before retrying.",
              file=sys.stderr)
    return result.exit_code
