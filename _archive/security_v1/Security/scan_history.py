"""Report everything a repository's history publishes about you. Read-only.

    python _archive/security_v1/Security/scan_history.py [REPO] [--all-refs | --ref REF ...] [--online]
                                    [--public-repo NAME] [--no-tailnet] [--show-values]

Reads every file version, every path, every commit message and every author / committer
identity reachable from the refs scanned -- by default the remote-tracking refs, which is what
the remote publishes (fetch first for a current answer); `--all-refs` adds local branches and
tags not yet pushed. Matches the shared rules in `Security/_patterns.py` plus the identity of
the person running it (see `scan_tree.py`). Values are masked unless `--show-values`.

What it cannot see: objects GitHub still serves for commits no ref reaches (old pull-request
heads, cached views), forks, and other people's clones. Exit status 1 when anything is found.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Security._history import public_refs, scan_history  # noqa: E402
from Security._report import render  # noqa: E402
from Security._repo import patterns_for, write_report  # noqa: E402
from Security._seeds import identity_seeds  # noqa: E402
from Security._rewrite import widen_seeds  # noqa: E402

EFFECT = "none"


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Report what a repository's history publishes.")
    parser.add_argument("repo", nargs="?", type=Path, default=Path("."))
    refs = parser.add_mutually_exclusive_group()
    refs.add_argument("--all-refs", action="store_true",
                      help="every local branch and tag too, not only what the remote has")
    refs.add_argument("--ref", action="append", metavar="REF", help="scan these refs only")
    parser.add_argument("--public-repo", action="append", default=[], metavar="NAME")
    parser.add_argument("--online", action="store_true",
                        help="also look for the GitHub organizations your gh login belongs to")
    parser.add_argument("--no-tailnet", action="store_true")
    parser.add_argument("--show-values", action="store_true",
                        help="print values instead of masking them (local use only)")
    parser.add_argument("--no-report", action="store_true",
                        help="do not write the full report file")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    chosen = args.ref or (["--all"] if args.all_refs else public_refs(repo))
    if not chosen:
        print("No remote-tracking refs to scan (nothing fetched?). Use --all-refs for local "
              "history.", file=sys.stderr)
        return 2
    seeds = identity_seeds(tailnet=not args.no_tailnet, online=args.online, cwd=repo)
    report = scan_history(repo, chosen, patterns_for(repo, seeds, args.public_repo))
    wider = widen_seeds(report, seeds)
    if wider:   # an old address of yours is on the commits: search the contents for it too
        report = scan_history(repo, chosen, patterns_for(repo, wider, args.public_repo))
    text, findings = render(report, args.show_values)
    print(text)
    if not args.no_report:
        full, _ = render(report, show_values=True)
        print(f"\nFull report, values unmasked (git-ignored, never published): "
              f"{write_report(repo, 'history', full)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
