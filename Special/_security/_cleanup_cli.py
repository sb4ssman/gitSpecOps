"""history clean: plan a history cleanup, then rewrite a NEW private mirror. Never the source.

`plan` reads a full private history report and your explicit choices, and can save the exact
plan (--plan-out). `rewrite` applies a saved plan into a new private folder. Because it rewrites
history, `rewrite` always needs a person: an attended terminal, the plan's id (--apply), and the
typed word REWRITE. There is no unattended way to run it. Nothing is ever published.
"""
import sys
from pathlib import Path

from Basic import _cli
from Special._runtime.cli_output import add_output_options, output_overrides
from Special._settings import SECURITY_ENGINES, SettingsError
from Special._security._cleanup import render, run_cleanup

COMMAND = "history clean"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser(COMMAND, "Plan a history cleanup, then rewrite a new private mirror (never the source).")
    commands = parser.add_subparsers(dest="action", required=True)
    plan = commands.add_parser("plan", help="choose findings and paths to remove, from a full private history report")
    plan.add_argument("source", type=Path, help="full private history scan report; raw values stay inside the tool")
    plan.add_argument("--choices", required=True, type=Path, help="your cleanup choices (JSON; see the source documentation)")
    plan.add_argument("--plan-out", type=Path, help="save the exact plan here, for rewrite")
    plan.add_argument("--include-remote-refs", action="store_true",
                      help="also include and keep remote-tracking refs; nothing is fetched")
    plan.add_argument("--engine", action="append", choices=("none", *SECURITY_ENGINES))
    rewrite = commands.add_parser("rewrite", help="rewrite a new private mirror from a saved plan; never the source")
    rewrite.add_argument("source", type=Path, help="the saved plan")
    rewrite.add_argument("--workspace", type=Path, required=True,
                         help="a new private folder outside the source; must not exist yet")
    _cli.add_apply(rewrite)
    for command in (plan, rewrite):
        _cli.add_json(command, sub=True)
        command.add_argument("--settings-home", type=Path, help="the same settings folder as when planning")
        add_output_options(command)
    args = parser.parse_args(argv)
    engines = getattr(args, "engine", None)
    if engines and "none" in engines and engines != ["none"]:
        parser.error("select none alone or a combination of engines")
    confirmation = None
    if args.action == "rewrite":
        if args.apply is None:
            parser.error("rewrite needs the plan's id: --apply PLAN_ID (shown when the plan was made)")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            parser.error("rewrite needs a person at a terminal; it has no unattended form")
        from Basic._station import ask, banner, notice
        if not _cli.machine(args):
            banner("Clean history  /  Rewrite", str(args.workspace))
            notice("This rewrites a NEW PRIVATE MIRROR",
                   "The source history is kept as it is, and nothing is published.", "warning")
        try:
            confirmation = ask("Type REWRITE to apply this exact saved plan:")
        except (EOFError, KeyboardInterrupt):
            confirmation = ""
        if confirmation != "REWRITE":
            return _cli.fail(args, COMMAND, "Cancelled; nothing was changed.", 130)
    try:
        overrides = output_overrides(args)
    except SettingsError as exc:
        return _cli.fail(args, COMMAND, f"{exc}; nothing was started.")
    result = run_cleanup("apply" if args.action == "rewrite" else "plan", args.source,
                         choices=getattr(args, "choices", None),
                         plan_out=getattr(args, "plan_out", None), workspace=getattr(args, "workspace", None),
                         home=getattr(args, "settings_home", None),
                         include_remote_refs=getattr(args, "include_remote_refs", False),
                         engines=None if engines is None else [] if engines == ["none"] else engines,
                         approve=getattr(args, "apply", None), confirmation=confirmation,
                         overrides=overrides)
    record = _cli.document(COMMAND, result.exit_code == 0, **result.record())

    def screen():
        from Basic._station import banner, line, say
        if args.action == "plan":
            banner("Clean history  /  Plan", str(args.source))
        say()
        for text in render(result, "text").splitlines():
            line(text)

    _cli.emit(args, record, screen)
    return result.exit_code
