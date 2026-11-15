"""secure-commit: check the named files, message and identity, then commit only an approved plan.

Without --apply it checks and shows the plan; a person at a terminal is asked, and a program
gets the plan id and the command that applies it. Help reads no settings. Output is the masked
result; Git's and hooks' own output stays private.
"""
from __future__ import annotations

import sys
from pathlib import Path

from Basic import _cli
from Special._security._commit.operation import commit_checked

COMMAND = "secure-commit"


def _show(result, banner, repo):
    from Basic._station import banner as draw, line, notice
    if banner:
        draw("Secure commit", str(repo))
    for text in result.summary().splitlines():
        line(text)
    tone = {"committed": "success", "ready": "success", "nothing-to-commit": "text"}.get(result.status, "warning")
    notice(result.status.replace("-", " ").capitalize(), "", tone)


def _code(result):
    if result.status in ("ready", "committed", "nothing-to-commit"):
        return _cli.OK
    return _cli.FAILED if result.status in ("blocked", "review-required", "hook-rejected") else _cli.USAGE


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser(COMMAND, "Check named working-tree files, message and identity before committing.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("paths", nargs="+", help="literal repo-relative files or tracked deletions, not directories")
    parser.add_argument("-m", "--message", required=True)
    parser.add_argument("--settings-home", type=Path)
    _cli.add_apply(parser)
    args = parser.parse_args(argv)

    def operation(apply, approve):
        return commit_checked(args.repo, args.paths, args.message, settings_home=args.settings_home,
                              apply=apply, approve=approve)

    return _cli.run_plan(args, COMMAND, argv, operation, ready=lambda r: r.status == "ready",
                         show=lambda r, b: _show(r, b, args.repo), record=lambda r: r.record(),
                         code=_code, question="Commit these files?")
