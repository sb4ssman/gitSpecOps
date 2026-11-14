"""Setup presentation over reviewed settings plans; never runs repository operations.

settings is guided/TTY-only. settings-preview and settings-save are noninteractive; saving
requires the exact preview id. Default summaries omit paths/keys/policy values. --show-paths
is a separate local-review channel showing paths only.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from Special._settings import SettingsError, resolve_document
from Special._settings.setup import COMPONENT, prepare_setup, save_setup

ACTIONS = ("settings", "settings-preview", "settings-save")
MATRIX = ("Participation choices:\n"
          "  One-off tools: Python/Git; GitHub operations also use your authenticated gh.\n"
          "  Saved updater preferences: roots, exclusions, reports and local logs; no fleet.\n"
          "  Fleet/state transports and live/recovery features: optional separate enrollment.\n"
          "  Desktop app/tray: optional installation over the same operations.\n"
          "This setup item saves updater preferences only; it performs no repository scan or update.")


def add_arguments(parser):
    """Attach the settings setup contract to the existing root setup parser."""
    parser.add_argument("--settings-home", type=Path, help="Selected user-data profile; no permanent relocation.")
    roots = parser.add_mutually_exclusive_group()
    roots.add_argument("--root", type=Path, action="append", help="Remember these updater roots; repeatable.")
    roots.add_argument("--clear-roots", action="store_true", help="Save empty roots; invocations use cwd unless --root is supplied.")
    parser.add_argument("--exclude-path", type=Path, action="append", help="Add component exclusions; repeatable.")
    parser.add_argument("--clear-exclusions", action="store_true", help="Replace component exclusions with supplied ones.")
    parser.add_argument("--output-mode", choices=("stdout", "file", "both"), help="Saved report routing preference.")
    parser.add_argument("--format", dest="saved_format", choices=("text", "json"), help="Saved report format preference.")
    parser.add_argument("--output-dir", type=Path, help="Saved report directory; does not itself enable file output.")
    parser.add_argument("--log", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))
    parser.add_argument("--log-max-bytes", type=int)
    parser.add_argument("--log-backups", type=int)
    parser.add_argument("--approve", metavar="REVIEW_ID", help="Exact id from settings-preview, required to save headlessly.")
    parser.add_argument("--json", action="store_true", help="Machine-readable setup result (not a saved output preference).")
    parser.add_argument("--show-paths", action="store_true", help="Explicitly reveal reviewed paths; never keys or policy values.")


def patch_from_args(args):
    patch = {}
    if args.root is not None or args.clear_roots:
        patch["scope"] = {"roots": [str(path.expanduser().resolve()) for path in args.root or []]}
    if args.exclude_path is not None:
        patch.setdefault("scope", {})["exclude_paths"] = [str(path.expanduser().resolve()) for path in args.exclude_path]
    for field, value in (("mode", args.output_mode), ("format", args.saved_format),
                          ("directory", str(args.output_dir.expanduser().resolve()) if args.output_dir is not None else None)):
        if value is not None:
            patch.setdefault("output", {})[field] = value
    for field, value in (("enabled", args.log), ("level", args.log_level), ("max_bytes", args.log_max_bytes),
                          ("backup_count", args.log_backups),
                          ("directory", str(args.log_dir.expanduser().resolve()) if args.log_dir is not None else None)):
        if value is not None:
            patch.setdefault("logging", {})[field] = value
    return patch


def print_plan(plan, *, json_output=False, show_paths=False):
    record = plan.summary()
    if show_paths:
        record["paths"] = plan.paths()
    if json_output:
        print(json.dumps(record, indent=2))
        return
    print(f"Updater settings: {record['target']} profile; ready for review")
    print(f"Review id: {plan.review_id}")
    print("Changes: " + (", ".join(plan.changes) or "none"))
    candidate = record["candidate"]
    print(f"Roots: {candidate['scope']['roots']}; exclusions: {candidate['scope']['exclude_paths']}")
    print(f"Reports: {candidate['output']['mode']}, {candidate['output']['format']}; "
          f"operational logging: {'on' if candidate['logging']['enabled'] else 'off'} ({candidate['logging']['level']})")
    if not candidate["scope"]["roots"]:
        print("No roots saved: the updater uses its current folder unless --root is supplied.")
    if show_paths:
        print(json.dumps(record["paths"], indent=2))
    print("Saving preferences performs no repository operation, enrollment or installation.")


def _choice(prompt, choices, default):
    while True:
        value = input(prompt).strip().lower() or default
        if value in choices:
            return value
        print("Choose one of the displayed options; nothing has been saved.")


def _paths(prompt):
    values = []
    print(prompt)
    while True:
        value = input("Folder (blank to finish): ").strip()
        if not value:
            return values
        values.append(str(Path(value).expanduser().resolve()))


def guided(args):
    """Gather/review with no writes, then invoke the writer only after typed SAVE."""
    if not sys.stdin.isatty():
        raise SettingsError("guided settings needs a terminal; use settings-preview/settings-save for assisted use")
    print(MATRIX)
    try:
        home = args.settings_home
        if home is None:
            selected = input("Settings home (blank uses the default user folder): ").strip()
            home = Path(selected) if selected else None
        changes = patch_from_args(args)
        initial = prepare_setup(home, changes, clear_exclusions=args.clear_exclusions)
        effective = resolve_document(initial.document, COMPONENT, home=initial.home).values
        if args.root is None and not args.clear_roots:
            if initial.expected_revision is None or _choice("Replace saved updater roots? [y/N]: ", ("y", "n"), "n") == "y":
                changes.setdefault("scope", {})["roots"] = _paths("Enter archive folders to remember. No scan will run.")
        if args.exclude_path is None and not args.clear_exclusions and _choice("Add exclusions? [y/N]: ", ("y", "n"), "n") == "y":
            changes.setdefault("scope", {})["exclude_paths"] = _paths("Enter exclusion folders; inherited exclusions remain.")
        mode = _choice(f"Report output [stdout/file/both] ({effective['output']['mode']}): ",
                       ("stdout", "file", "both"), effective["output"]["mode"])
        changes.setdefault("output", {})["mode"] = mode
        changes["output"]["format"] = _choice(f"Report format [text/json] ({effective['output']['format']}): ",
                                               ("text", "json"), effective["output"]["format"])
        if mode != "stdout":
            value = input("Report directory (blank keeps the selected default): ").strip()
            if value:
                changes["output"]["directory"] = str(Path(value).expanduser().resolve())
        logging_now = "y" if effective["logging"]["enabled"] else "n"
        enabled = _choice(f"Local counts-only logging? [y/n] ({logging_now}): ", ("y", "n"), logging_now) == "y"
        changes.setdefault("logging", {})["enabled"] = enabled
        if enabled:
            value = input("Log directory (blank keeps the selected default): ").strip()
            if value:
                changes["logging"]["directory"] = str(Path(value).expanduser().resolve())
        initial.verify()
        plan = prepare_setup(initial.home, changes, clear_exclusions=args.clear_exclusions)
        plan = replace(plan, home_source=initial.home_source)
        print_plan(plan, show_paths=args.show_paths)
        if input('Type SAVE to write these preferences, or anything else to cancel: ').strip() != "SAVE":
            print("Cancelled; no settings were saved.")
            return 0
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled before save; no settings were saved.")
        return 0
    save_setup(plan, plan.review_id)
    print("Settings saved." if plan.changes else "Settings already match; nothing was written.")
    if plan.home_source == "explicit":
        print("Select this profile per invocation via --settings-home or GITSPECOPS_HOME; no locator was changed.")
    return 0


def dispatch(args):
    """Return an exit code; no setup action grants repository-operation authority."""
    try:
        if args.action == "settings":
            return guided(args)
        if args.action == "settings-save" and args.approve is None:
            raise SettingsError("settings-save requires --approve with an id from settings-preview")
        plan = prepare_setup(args.settings_home, patch_from_args(args), clear_exclusions=args.clear_exclusions)
        if args.action == "settings-preview":
            print_plan(plan, json_output=args.json, show_paths=args.show_paths)
            return 0
        save_setup(plan, args.approve)
        record = {"status": "saved" if plan.changes else "unchanged", "component": COMPONENT,
                  "runs_operations": False}
        if args.show_paths:
            record["paths"] = plan.paths()
        print(json.dumps(record) if args.json else
              ("Settings saved." if plan.changes else "Settings already match; nothing was written."))
        if args.show_paths and not args.json:
            print(json.dumps(record["paths"], indent=2))
        return 0
    except SettingsError as exc:
        if args.json:
            print(json.dumps({"status": "error", "message": str(exc)}))
        else:
            print(f"Settings error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        message = "Settings operation could not finish; inspect the selected profile before retrying."
        print(json.dumps({"status": "error", "message": message}) if args.json else message,
              file=sys.stdout if args.json else sys.stderr)
        return 2
    except KeyboardInterrupt:
        message = "Settings save was interrupted; inspect the selected profile before retrying."
        print(json.dumps({"status": "interrupted", "message": message}) if args.json else message,
              file=sys.stdout if args.json else sys.stderr)
        return 130
