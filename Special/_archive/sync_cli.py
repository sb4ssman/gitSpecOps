"""Archive sync CLI over the shared runner; help performs no setup.

Default: plan to stdout. Saved output/log preferences apply unless explicitly overridden.
Mutations require --yes outside a terminal, or interactive approval of the masked plan.
Publication is separate from pull/clone/repair and checks outgoing history before each push.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

from Basic._console import enable_unicode_output
from Basic._run import DEFAULT_GIT_TIMEOUT_SECONDS, set_git_timeout
from Special._archive.operation import error_message, render_result, run_archives
from Special._archive.plan import DEFAULT_APPROVED_REMOTE_PREFIXES
from Special._archive.sync import DEFAULT_PUBLISH_PAUSE_SECONDS
from Special._runtime.cli_output import add_output_options, output_overrides
from Special._settings import SettingsError, _absolute, resolve_settings


def build_parser():
    """One direct/launcher parser; validate actions before resolving settings."""
    parser = argparse.ArgumentParser(description="Plan archives; explicitly apply update, sync, repairs or publication.")
    parser.add_argument("--root", type=Path, action="append", help="Archive root; repeatable. Otherwise saved roots or cwd.")
    parser.add_argument("--settings-home", type=Path, help="Select one settings home; no conversion or fallback.")
    parser.add_argument("--github-owner", help="Override discovered provider owner.")
    parser.add_argument("--approved-remote-prefix", action="append", help="Allowed origin/clone/push prefix; repeatable.")
    verbs = parser.add_mutually_exclusive_group()
    verbs.add_argument("--update", action="store_true", help="Fast-forward eligible existing repositories.")
    verbs.add_argument("--sync", action="store_true", help="Update and clone missing repositories.")
    verbs.add_argument("--publish", action="store_true", help="Check and push ahead-only exact tips; never force or commit.")
    parser.add_argument("--reconcile", action="store_true", help="Explicitly repair stale origin URLs.")
    parser.add_argument("--rename-folders", action="store_true", help="Explicitly rename clean folders to upstream names.")
    parser.add_argument("--include-dirty", action="store_true", help="With publish, allow committed work in a dirty checkout.")
    parser.add_argument("--publish-pause", type=float, help="Seconds between pushes; default 1.")
    parser.add_argument("--dry-run", action="store_true", help="Plan selected actions without applying them; sinks still apply.")
    parser.add_argument("--yes", action="store_true", help="Approve selected current plans without prompts.")
    parser.add_argument("--git-timeout", type=int, default=DEFAULT_GIT_TIMEOUT_SECONDS)
    add_output_options(parser)
    return parser


def _approve(action, plan):
    """Prompt on stderr, preserving stdout for one machine-readable final result."""
    print(json.dumps(plan, indent=2), file=sys.stderr)
    word = "PUBLISH" if action == "publish" else "APPLY"
    print(f"Type {word} to approve this {action} plan: ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip() == word


def main(argv=None):
    enable_unicode_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.publish and (args.reconcile or args.rename_folders):
        parser.error("publication cannot be combined with repairs; run it separately")
    if (args.include_dirty or args.publish_pause is not None) and not args.publish:
        parser.error("--include-dirty/--publish-pause require --publish")
    if args.publish_pause is not None and (not math.isfinite(args.publish_pause) or args.publish_pause < 0):
        parser.error("publish pause must be finite and nonnegative")
    if args.git_timeout < 1:
        parser.error("git timeout must be positive")
    prefixes = args.approved_remote_prefix or list(DEFAULT_APPROVED_REMOTE_PREFIXES)
    if any(not prefix.strip() for prefix in prefixes):
        parser.error("allowed remote prefixes must be nonempty strings")
    mutating = args.update or args.sync or args.publish or args.reconcile or args.rename_folders
    scan_only = args.dry_run or not mutating
    if not scan_only and not args.yes and not sys.stdin.isatty():
        parser.error("mutating actions outside a terminal require --yes; use --dry-run to preview")
    try:
        overrides = output_overrides(args)
        settings = resolve_settings("archive_sync", home=args.settings_home, overrides=overrides)
        snapshot = copy.deepcopy((settings.values, settings.configured, settings.schema_version))
        def verify():
            current = resolve_settings("archive_sync", home=settings.home, overrides=overrides)
            if (current.values, current.configured, current.schema_version) != snapshot:
                raise SettingsError("selected settings changed")
        roots = args.root or settings.values["scope"]["roots"] or [Path.cwd()]
        mode = "publish" if args.publish else "sync" if args.sync else "update" if args.update else "repair" if mutating else "scan"
        requests = [{"root": str(_absolute(root, Path.cwd())), "mode": mode,
                     "approved_remote_prefixes": prefixes, "owner_override": args.github_owner,
                     "reconcile": args.reconcile, "rename_folders": args.rename_folders,
                     "include_dirty": args.include_dirty,
                     "publish_pause": args.publish_pause if args.publish_pause is not None else DEFAULT_PUBLISH_PAUSE_SECONDS}
                    for root in roots]
        set_git_timeout(args.git_timeout)
        result = run_archives(settings, requests, scan_only=scan_only, before_action=verify,
                              approve=(lambda *_: True) if args.yes else _approve)
    except SettingsError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 2
    if settings.values["output"]["mode"] in ("stdout", "both"):
        print(render_result(result, settings.values["output"]["format"]))
    else:
        for artifact in result.record()["artifacts"]:
            print(f"{artifact['kind']}: {artifact['path']}", file=sys.stderr)
    for code in result.errors:
        print("Error: " + error_message(code), file=sys.stderr)
    return result.exit_code
