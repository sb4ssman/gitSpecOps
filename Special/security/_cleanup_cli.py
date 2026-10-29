"""Thin plan/apply adapter; no confirmation flags, raw-value output or publication route."""
import argparse
import sys
from pathlib import Path

from Special._runtime.cli_output import add_output_options, output_overrides
from Special._settings import SECURITY_ENGINES, SettingsError
from Special.security._cleanup import render, run_cleanup


def main(argv=None):
    parser = argparse.ArgumentParser(description="DANGEROUS HISTORY MAINTENANCE: plan and prove a new private mirror only.")
    commands = parser.add_subparsers(dest="action", required=True)
    plan = commands.add_parser("plan", help="Choose explicit findings/paths using a full private history report.")
    plan.add_argument("source", type=Path, help="Full private scan-history report; raw values stay inside the tool.")
    plan.add_argument("--choices", required=True, type=Path, help="Explicit private cleanup-choice JSON; see source documentation.")
    plan.add_argument("--plan-out", type=Path, help="Exclusively save the private exact plan for later application.")
    plan.add_argument("--include-remote-refs", action="store_true", help="Explicitly include and preserve tracking refs and their symbolic aliases; no fetch.")
    plan.add_argument("--engine", action="append", choices=("none", *SECURITY_ENGINES))
    apply = commands.add_parser("apply", help="Rewrite a new private mirror from a saved plan; never the source.")
    apply.add_argument("source", type=Path, help="Saved cleanup plan.")
    apply.add_argument("--workspace", type=Path, required=True, help="New private directory outside the source; must not exist.")
    apply.add_argument("--approve", required=True, help="Exact saved plan id from preview.")
    for command in (plan, apply):
        command.add_argument("--settings-home", type=Path, help="Selected profile; apply must use the same home as planning.")
        command.add_argument("--legacy-policy", action="store_true", help="Explicit existing text policy; cannot bypass common settings.")
        add_output_options(command)
    args = parser.parse_args(argv)
    engines = getattr(args, "engine", None)
    if engines and "none" in engines and engines != ["none"]:
        parser.error("select none alone or a combination of engines")
    confirmation = None
    if args.action == "apply":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("application requires an attended terminal; there is no --yes or confirmation flag")
        print("This rewrites a NEW PRIVATE MIRROR. Source history is retained; no publication is performed.", file=sys.stderr)
        print("Type REWRITE to apply this exact saved plan:", file=sys.stderr)
        try:
            confirmation = input()
        except (EOFError, KeyboardInterrupt):
            print("Cancelled.", file=sys.stderr)
            return 130
        if confirmation != "REWRITE":
            print("Cancelled.", file=sys.stderr)
            return 130
    try:
        overrides = output_overrides(args)
    except SettingsError:
        parser.error("conflicting output options; no operation started")
    result = run_cleanup(args.action, args.source, choices=getattr(args, "choices", None),
                         plan_out=getattr(args, "plan_out", None), workspace=getattr(args, "workspace", None),
                         home=getattr(args, "settings_home", None), legacy_policy=getattr(args, "legacy_policy", False),
                         include_remote_refs=getattr(args, "include_remote_refs", False),
                         engines=None if engines is None else [] if engines == ["none"] else engines,
                         approve=getattr(args, "approve", None), confirmation=confirmation,
                         overrides=overrides)
    if result.delivery["mode"] != "file":
        print(render(result, result.delivery["format"]))
    else:
        for artifact in result.record()["artifacts"]:
            print(f"Produced {artifact['kind']}: {artifact['path']} ({artifact['disclosure']})", file=sys.stderr)
    return result.exit_code
