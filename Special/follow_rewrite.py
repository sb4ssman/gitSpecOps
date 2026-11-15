"""Move this machine's clones onto a rewritten history, and update the commit ids their files quote.

Why:          after clean_history rewrites a repository and the forced push is made, every
              older clone must follow, or a push from it publishes the old history again.
Reads:        the checkouts under the given folders; the rewrite workspace's commit map.
May change:   `follow`, once its plan is approved: `git reset --keep` of each safe checkout onto
              its rewritten upstream; a checkout with unpushed or uncommitted work is refused.
              `relink`, once its plan is approved: quoted commit ids in tracked text files,
              left uncommitted for review. Nothing is committed or pushed.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once. Other machines: Elaborate/follow_rewrite_fleet.py.
Status:       working

    gitso follow-rewrite follow [PATH ...] [--match TEXT] [--depth N] [--apply PLAN_ID]
    gitso follow-rewrite relink WORKSPACE [WORKSPACE ...] --checkout PATH [--apply PLAN_ID]
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

EFFECT = "local"


COMMAND = "follow-rewrite"


def main(argv=None) -> int:
    from Basic import _cli
    from Basic._console import enable_unicode_output
    from Special._security.follow import assess, move, relink, repositories_under

    enable_unicode_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser(COMMAND, __doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    follow = commands.add_parser("follow", help="move safe pre-rewrite clones onto the new history")
    follow.add_argument("paths", nargs="*", type=Path, default=[Path.cwd()],
                        help="checkouts or folders holding them (default: here)")
    follow.add_argument("--match", action="append", default=[],
                        help="only checkouts whose origin URL contains this text (repeatable)")
    follow.add_argument("--depth", type=int, default=3, help="folder depth to search (default 3)")
    follow.add_argument("--no-fetch", action="store_true", help="use the remote refs already fetched")
    linked = commands.add_parser("relink", help="update commit ids quoted in a checkout's files")
    linked.add_argument("workspaces", nargs="+", type=Path, help="rewrite workspace(s) from clean-history")
    linked.add_argument("--checkout", type=Path, required=True, help="the checkout to update")
    for command in (follow, linked):
        _cli.add_json(command, sub=True)
        _cli.add_apply(command)
    args = parser.parse_args(argv)
    approval = _cli.Approval(args, COMMAND, argv)
    try:
        if args.command == "relink":
            lines, total = relink(args.workspaces, args.checkout)
            plan = {"action": "relink", "checkout": str(args.checkout), "quoted_ids": lines}

            def show_relink():
                from Basic._station import banner, line, say
                banner("Follow a rewrite  /  Relink", str(args.checkout))
                say()
                for text in lines or ["No quoted commit ids found."]:
                    line(text)

            if not approval.decide(plan, show_relink, nothing_to_do=not total,
                                   question=f"Update these {total} quoted ids (left uncommitted)?"):
                return approval.code
            lines, total = relink(args.workspaces, args.checkout, write=True)
            return _cli.report(args, COMMAND, ok=True, page="Follow a rewrite  /  Relinked",
                               context=(str(args.checkout),), output="\n".join(lines),
                               message=f"{total} quoted id(s) updated, not committed.", updated=total)

        repos = repositories_under(args.paths, match=args.match, depth=args.depth)
        if not repos:
            return _cli.fail(args, COMMAND, "No matching repositories found.")
        if not _cli.machine(args):
            from Basic._station import banner, line
            banner("Follow a rewrite", f"{len(repos)} checkout(s)")
            line(f"Checking {len(repos)} (fetching each)...", "detail")
        results = [assess(repo, fetch=not args.no_fetch) for repo in repos]
        moves = [r for r in results if r["action"] == "move"]
        refused = [r for r in results if r["action"] == "refuse"]
        current = [r for r in results if r["action"] in ("current", "skip")]
        plan = {"action": "follow", "moves": [{key: str(r[key]) for key in ("repo", "branch", "old_tip", "new_tip")}
                                                for r in moves],
                "refused": [{"repo": str(r["repo"]), "why": r["why"], "hint": r["hint"]} for r in refused],
                "current": len(current)}

        def show_follow():
            from Basic._station import row, say, section
            section("Already current, or nothing to follow")
            row("Checkouts", len(current))
            if refused:
                section(f"Refused; nothing will change in these ({len(refused)})")
                for r in refused:
                    row(Path(r["repo"]).name, r["why"] + (f" {r['hint']}" if r["hint"] else ""), "warning")
            if moves:
                section(f"To move onto the rewritten history ({len(moves)})")
                for r in moves:
                    row(Path(r["repo"]).name, f"{r['branch']}: {r['old_tip']} -> {r['new_tip']}")
            say()

        if not approval.decide(plan, show_follow, nothing_to_do=not moves,
                               question=f"Move these {len(moves)} now?"):
            return approval.code if moves or not refused else _cli.FAILED
        failed = sum(not move(r) for r in moves)
        return _cli.report(args, COMMAND, ok=not (failed or refused), page="Follow a rewrite  /  Moved",
                           message=f"Moved {len(moves) - failed}; refused {len(refused)}; failed {failed}. "
                                   "The old commits stay in each clone's reflog, on no branch; nothing pushes them.",
                           moved=len(moves) - failed, refused=len(refused), failed=failed)
    except (OSError, ValueError) as exc:
        return _cli.fail(args, COMMAND, f"{exc}.")


if __name__ == "__main__":
    raise SystemExit(main())
