"""secure-push: plan one branch push, then check outgoing history before publishing.

Without --apply it shows the plan; a person at a terminal is asked, and a program gets the plan
id and the command that applies it. Applying fetches, checks the actual outgoing history and
pushes only that plan. Only masked checking and plain errors are printed; nothing is saved.
"""
from __future__ import annotations

import sys
from pathlib import Path

from Basic import _cli
from Special._security._push import push_checked

COMMAND = "secure-push"


def _show(result, banner, repo):
    from Basic._station import banner as draw, line, notice
    if banner:
        draw("Secure push", str(repo))
    if result.report is not None:
        for text in result.report.summary().splitlines():
            line(text)
    tone = {"pushed": "success", "planned": "success", "already-current": "text"}.get(result.status, "warning")
    notice(result.status.replace("-", " ").capitalize(), result.message, tone)


def _code(result):
    if result.status in ("planned", "pushed", "already-current"):
        return _cli.OK
    return _cli.FAILED if result.status in ("blocked", "review-required") else _cli.USAGE


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser(COMMAND, "Plan one branch push, then check outgoing history before publishing.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--settings-home", type=Path)
    _cli.add_apply(parser)
    args = parser.parse_args(argv)

    def operation(apply, approve):
        return push_checked(args.repo, settings_home=args.settings_home, apply=apply, approve=approve)

    return _cli.run_plan(args, COMMAND, argv, operation, ready=lambda r: r.status == "planned",
                         show=lambda r, b: _show(r, b, args.repo), record=lambda r: r.record(),
                         code=_code, question="Push this branch?")
