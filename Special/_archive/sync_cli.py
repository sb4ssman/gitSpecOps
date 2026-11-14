"""archive sync: plan, then apply, update, sync, repairs or publication for folders of clones.

Choose what to plan with --update, --sync or --publish (and the repairs --reconcile and
--rename-folders); with none of them it only inspects. Without --apply nothing changes: a person
at a terminal is asked about each folder's plan, and a program gets each plan's id and the
command that applies them. Publication is separate from pulls, clones and repairs, and checks
outgoing history before each push. Help reads no settings.
"""
from __future__ import annotations

import copy
import math
import sys
from pathlib import Path

from Basic import _cli
from Basic._console import enable_unicode_output
from Basic._run import DEFAULT_GIT_TIMEOUT_SECONDS, set_git_timeout
from Special._archive.operation import error_message, render_result, run_archives
from Special._archive.plan import DEFAULT_APPROVED_REMOTE_PREFIXES
from Special._archive.sync import DEFAULT_PUBLISH_PAUSE_SECONDS
from Special._runtime.cli_output import add_output_options, output_overrides
from Special._settings import SettingsError, _absolute, resolve_settings

COMMAND = "archive sync"


def build_parser():
    parser = _cli.parser(COMMAND, "Plan archives, then apply updates, clones, repairs or publication.")
    parser.add_argument("--root", type=Path, action="append",
                        help="a folder of clones; repeatable (default: the saved folders, else this folder)")
    parser.add_argument("--settings-home", type=Path, help="use the settings in this folder instead")
    parser.add_argument("--github-owner", help="the GitHub owner to compare with, instead of the one found")
    parser.add_argument("--allowed-remote", action="append",
                        help="only origins, clone and push addresses starting with this; repeatable (default: GitHub)")
    verbs = parser.add_mutually_exclusive_group()
    verbs.add_argument("--update", action="store_true", help="plan fast-forwards of existing repositories")
    verbs.add_argument("--sync", action="store_true", help="plan fast-forwards and clones of missing repositories")
    verbs.add_argument("--publish", action="store_true", help="plan pushes of ahead-only work; never forced, never commits")
    parser.add_argument("--reconcile", action="store_true", help="also plan repairs of outdated origin addresses")
    parser.add_argument("--rename-folders", action="store_true", help="also plan renaming clean folders to their repository names")
    parser.add_argument("--include-dirty", action="store_true", help="with --publish, include committed work in a checkout with uncommitted edits")
    parser.add_argument("--publish-pause", type=float, help="seconds between pushes (default 1)")
    parser.add_argument("--git-timeout", type=int, default=DEFAULT_GIT_TIMEOUT_SECONDS)
    add_output_options(parser)
    _cli.add_apply(parser, many=True)
    return parser


def main(argv=None):
    enable_unicode_output()
    argv = list(sys.argv[1:] if argv is None else argv)
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
    prefixes = args.allowed_remote or list(DEFAULT_APPROVED_REMOTE_PREFIXES)
    if any(not prefix.strip() for prefix in prefixes):
        parser.error("allowed remote prefixes must be nonempty")
    mutating = args.update or args.sync or args.publish or args.reconcile or args.rename_folders
    screen = not _cli.machine(args)
    gate = _cli.Gate(args, COMMAND, argv, lambda action, plan, identity: _cli.outline(
        f"{action.capitalize()} plan", plan, identity))
    try:
        overrides = output_overrides(args)
        settings = resolve_settings("archive_sync", home=args.settings_home, overrides=overrides)
        snapshot = copy.deepcopy((settings.values, settings.configured, settings.schema_version))

        def verify():
            current = resolve_settings("archive_sync", home=settings.home, overrides=overrides)
            if (current.values, current.configured, current.schema_version) != snapshot:
                raise SettingsError("selected settings changed")
        roots = args.root or settings.values["scope"]["roots"] or [Path.cwd()]
        mode = ("publish" if args.publish else "sync" if args.sync else "update" if args.update
                else "repair" if mutating else "scan")
        requests = [{"root": str(_absolute(root, Path.cwd())), "mode": mode,
                     "approved_remote_prefixes": prefixes, "owner_override": args.github_owner,
                     "reconcile": args.reconcile, "rename_folders": args.rename_folders,
                     "include_dirty": args.include_dirty,
                     "publish_pause": args.publish_pause if args.publish_pause is not None else DEFAULT_PUBLISH_PAUSE_SECONDS}
                    for root in roots]
        set_git_timeout(args.git_timeout)
        if screen:
            from Basic._station import banner
            banner("Sync archive", "  |  ".join(request["root"] for request in requests))
        result = run_archives(settings, requests, scan_only=not mutating, before_action=verify, approve=gate)
    except SettingsError as exc:
        return _cli.fail(args, COMMAND, f"Settings: {exc}.")
    unused = gate.unused()
    record = _cli.document(COMMAND, result.exit_code == 0 and not unused, **result.record())
    record["plans"] = [{"action": item["action"], "plan_id": item["plan_id"]} for item in gate.offered]
    if gate.apply_line():
        record["apply"] = gate.apply_line()
    if unused:
        record["error"] = ("These plan ids match no current plan, so nothing in those plans was done "
                           "(something changed): " + ", ".join(unused))
    errors = [error_message(code) for code in result.errors]
    if errors:
        record["messages"] = errors

    def show():
        from Basic._station import line, notice, say
        say()
        for text in render_result(result, "text").splitlines():
            line(text)
        for text in errors:
            notice("Stopped", text, "error")
        if unused:
            notice("Plan changed", record["error"], "warning")
        if gate.offered:
            notice("Not applied", "Nothing was changed. To apply these plans without being asked:")
            line(record["apply"], "detail")

    _cli.emit(args, record, show)
    return _cli.PLAN_CHANGED if unused else result.exit_code
