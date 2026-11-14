"""archive update: fast-forward the eligible repositories in folders of clones.

Without --apply it inspects each folder and shows its plan, changing nothing; a person at a
terminal is asked about each folder's plan, and a program gets each plan's id and the command
that applies them. Help reads no settings.
"""
from __future__ import annotations

import sys
from pathlib import Path

from Basic import _cli
from Basic._console import enable_unicode_output
from Basic._run import DEFAULT_GIT_TIMEOUT_SECONDS, set_git_timeout
from Special._archive.update_operation import UpdateRequest, explain_error, render_result, run_update
from Special._archive.plan import DEFAULT_APPROVED_REMOTE_PREFIXES
from Special._runtime.cli_output import add_output_options, output_overrides
from Special._settings import SettingsError, resolve_settings, _absolute

COMMAND = "archive update"


def build_parser():
    parser = _cli.parser(COMMAND, "Fast-forward the eligible repositories in folders of clones; "
                                  "shows the plan first.")
    parser.add_argument("--root", type=Path, action="append",
                        help="a folder of clones; repeatable (default: the saved folders, else this folder)")
    parser.add_argument("--exclude-path", type=Path, action="append", help="a folder never to touch; repeatable")
    parser.add_argument("--settings-home", type=Path, help="use the settings in this folder instead")
    parser.add_argument("--allowed-remote", action="append",
                        help="only repositories whose origin starts with this; repeatable (default: GitHub)")
    parser.add_argument("--show-remote-urls", action="store_true", help="show origins (credentials still hidden)")
    parser.add_argument("--git-timeout", type=int, default=DEFAULT_GIT_TIMEOUT_SECONDS)
    add_output_options(parser)
    _cli.add_apply(parser, many=True)
    return parser


def operation_settings(args):
    """Resolve once; paths given here are relative to this folder, saved ones to the settings home."""
    if args.git_timeout < 1:
        raise SettingsError("git timeout must be positive")
    overrides = output_overrides(args)
    if args.root is not None:
        overrides.setdefault("scope", {})["roots"] = [str(_absolute(path, Path.cwd())) for path in args.root]
    if args.exclude_path is not None:
        overrides.setdefault("scope", {})["exclude_paths"] = [str(path.resolve()) for path in args.exclude_path]
    return resolve_settings("archive_update", home=args.settings_home, overrides=overrides)


def main(argv=None) -> int:
    enable_unicode_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        settings = operation_settings(args)
    except SettingsError as exc:
        return _cli.fail(args, COMMAND, f"Settings: {exc}.")
    set_git_timeout(args.git_timeout)
    roots = "  |  ".join(str(root) for root in settings.values["scope"]["roots"]) or str(Path.cwd())
    screen = not _cli.machine(args)
    if screen:
        from Basic._station import banner
        banner("Update archive", roots)
    gate = _cli.Gate(args, COMMAND, argv, lambda action, plan, identity: _cli.outline(
        f"Update plan for {', '.join(root['scan']['root'] for root in plan.get('roots', []))}", plan, identity))
    request = UpdateRequest(scan_only=False,
                            approved_prefixes=tuple(args.allowed_remote or DEFAULT_APPROVED_REMOTE_PREFIXES))
    result = run_update(settings, request, show_remote_urls=args.show_remote_urls,
                        progress=(lambda text: print(text, file=sys.stderr)) if screen else None,
                        approve=lambda plan: gate("update", plan))
    unused = gate.unused()
    record = _cli.document(COMMAND, result.exit_code == 0 and not unused,
                           **result.record(show_remote_urls=args.show_remote_urls))
    record["plans"] = [{"action": item["action"], "plan_id": item["plan_id"]} for item in gate.offered]
    if gate.apply_line():
        record["apply"] = gate.apply_line()
    if unused:
        record["error"] = ("These plan ids match no current plan, so nothing in those plans was done "
                           "(something changed): " + ", ".join(unused))
    errors = [f"{explain_error(error)} Review the result before retrying." for error in result.errors]
    if errors:
        record["messages"] = errors

    def show():
        from Basic._station import line, notice, say
        say()
        for text in render_result(result, "text", show_remote_urls=args.show_remote_urls).splitlines():
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
