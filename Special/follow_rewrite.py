"""Move this machine's clones onto a rewritten history, and update the commit ids their files quote.

Why:          after clean_history rewrites a repository and the forced push is made, every
              older clone must follow, or a push from it publishes the old history again.
Reads:        the checkouts under the given folders; the rewrite workspace's commit map.
May change:   `follow`: after one confirmation, `git reset --keep` of each safe checkout onto
              its rewritten upstream; a checkout with unpushed or uncommitted work is refused.
              `relink --write`: quoted commit ids in tracked text files, left for review.
              Nothing is committed or pushed (use commit_repo.py and push_repo.py).
Results:      plans and results on stdout.
Layer:        Special: this machine, once. Other machines: Elaborate/follow_rewrite_fleet.py.
Status:       working

    python Special/follow_rewrite.py follow [PATH ...] [--match TEXT] [--depth N] [--yes]
    python Special/follow_rewrite.py relink WORKSPACE [WORKSPACE ...] --checkout PATH [--write]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

EFFECT = "local"


def main(argv=None) -> int:
    from Basic._console import enable_unicode_output
    from Special._security.follow import follow_many, relink

    enable_unicode_output()
    parser = argparse.ArgumentParser(prog="follow_rewrite", description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    follow = commands.add_parser("follow", help="move safe pre-rewrite clones onto the new history")
    follow.add_argument("paths", nargs="*", type=Path, default=[Path.cwd()],
                        help="checkouts or folders holding them (default: here)")
    follow.add_argument("--match", action="append", default=[],
                        help="only checkouts whose origin URL contains this text (repeatable)")
    follow.add_argument("--depth", type=int, default=3, help="folder depth to search (default 3)")
    follow.add_argument("--no-fetch", action="store_true", help="use the remote refs already fetched")
    follow.add_argument("--yes", action="store_true", help="move without asking, after the plan prints")
    linked = commands.add_parser("relink", help="update commit ids quoted in a checkout's files")
    linked.add_argument("workspaces", nargs="+", type=Path, help="rewrite workspace(s) from clean_history")
    linked.add_argument("--checkout", type=Path, required=True, help="the checkout to update")
    linked.add_argument("--write", action="store_true", help="edit the files (left uncommitted)")
    args = parser.parse_args(argv)
    try:
        if args.command == "follow":
            return follow_many(args.paths, match=args.match, depth=args.depth,
                               fetch=not args.no_fetch, assume_yes=args.yes)
        lines, total = relink(args.workspaces, args.checkout, write=args.write)
        print("\n".join(lines) or "No quoted commit ids found.")
        if total:
            print(f"{total} quoted id(s) {'updated, not committed' if args.write else 'found; --write updates them'}.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
