"""review: accept one scoped finding as reviewed, or revoke a review, by approved plan.

Without --apply it reads the full private report, shows the plan and writes nothing; a person at
a terminal is asked, and a program gets the plan id. Applying saves one private, unchangeable
decision (or its revocation). No raw reason or value is printed, no settings are edited and no
Git action is performed.
"""
import sys
from pathlib import Path

from Basic import _cli
from Special._security._review_operation import review_finding

COMMAND = "review"


def _show(result, banner, report):
    from Basic._station import banner as draw, notice, row, say
    if banner:
        draw("Review a finding", str(report))
    if result.scope:
        scope = result.scope
        say()
        row("Finding", f"{scope['finding_id']} [{scope['severity']}] {scope['check']}")
        row("Where", f"{scope['where']}:{scope['line']}")
        row("Value", scope["value"])
    if result.review_id:
        row("Review", result.review_id)
    for artifact in result.artifacts:
        row(f"Produced {artifact['kind']}", f"{artifact['path']} ({artifact['disclosure']})")
    ok = result.status in ("planned", "accepted", "revoked", "already-reviewed")
    notice(result.status.replace("-", " ").capitalize(), result.message, "success" if ok else "warning")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser(COMMAND, "Accept one finding as reviewed, or revoke a review, by an approved plan.")
    parser.add_argument("report", type=Path, help="Full private report created by scan or history scan, with --out.")
    parser.add_argument("finding", nargs="?", help="Report-local finding id; selects scope, never authorizes a save.")
    parser.add_argument("--revoke", help="Revoke one active review id instead of accepting a finding.")
    parser.add_argument("--reason", required=True, help="Private explanation; never echoed to normal output.")
    parser.add_argument("--settings-home", type=Path)
    _cli.add_apply(parser)
    args = parser.parse_args(argv)
    if bool(args.finding) == bool(args.revoke):
        parser.error("select a finding or --revoke, not both")

    def operation(apply, approve):
        return review_finding(args.report, args.finding, args.reason, home=args.settings_home,
                              apply=apply, approve=approve, revoke=args.revoke)

    return _cli.run_plan(
        args, COMMAND, argv, operation, ready=lambda r: r.status == "planned",
        show=lambda r, b: _show(r, b, args.report), record=lambda r: r.record(),
        code=lambda r: _cli.OK if r.status in ("planned", "accepted", "revoked", "already-reviewed") else _cli.USAGE,
        question="Save this review?", hidden=("--reason",))
