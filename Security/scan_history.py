"""Report everything a repository's history publishes about you. Read-only.

    python Security/scan_history.py [REPO] [--all-refs | --ref REF ...] [--online]
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
from Security._history import HistoryReport, public_refs, scan_history  # noqa: E402
from Security._patterns import SECRETS, mask  # noqa: E402
from Security._repo import patterns_for  # noqa: E402
from Security._seeds import identity_seeds  # noqa: E402

EFFECT = "none"


def render(report: HistoryReport, show_values: bool = False) -> tuple[str, int]:
    """The report text and the number of findings."""
    shown = (lambda value: value) if show_values else mask
    lines = [f"Scanned {report.commits} commit(s), {report.blobs} file version(s), "
             f"{report.objects} object(s) reachable from: {', '.join(report.refs)}"]
    findings = 0
    people = report.personal_identities()
    if people:
        lines.append("\nCommit identities (published on every commit page and .patch URL):")
        for person in sorted(people, key=lambda p: -p.commits):
            findings += 1
            lines.append(f"  {shown(person.email)} / {shown(person.name)}: {person.concern} — "
                         f"{person.commits} commit(s), {person.first[:10]} to {person.last[:10]}")
    secrets = [e for e in report.exposures.values() if e.kind in SECRETS]
    others = [e for e in report.exposures.values() if e.kind not in SECRETS]
    for title, group in (("Secrets — rotate these first; removing them does not un-publish them",
                          secrets), ("Personal data in files, paths or messages", others)):
        if not group:
            continue
        lines.append(f"\n{title}:")
        for exposure in sorted(group, key=lambda e: (e.kind, e.value)):
            findings += 1
            where = []
            if exposure.paths:
                sample = ", ".join(sorted(exposure.paths)[:3])
                more = len(exposure.paths) - 3
                where.append(f"in {len(exposure.paths)} file path(s): {sample}"
                             + (f" (+{more} more)" if more > 0 else ""))
            if exposure.in_paths:
                where.append(f"in {len(exposure.in_paths)} file name(s)")
            if exposure.commits:
                where.append(f"in {len(exposure.commits)} commit message(s)")
            state = "STILL IN CURRENT FILES" if exposure.current else "history only"
            lines.append(f"  {exposure.kind}: {shown(exposure.value)!r} [{state}]")
            lines.extend(f"      {item}" for item in where)
    if not findings:
        lines.append("Nothing found.")
    return "\n".join(lines), findings


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
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    chosen = args.ref or (["--all"] if args.all_refs else public_refs(repo))
    if not chosen:
        print("No remote-tracking refs to scan (nothing fetched?). Use --all-refs for local "
              "history.", file=sys.stderr)
        return 2
    seeds = identity_seeds(tailnet=not args.no_tailnet, online=args.online, cwd=repo)
    report = scan_history(repo, chosen, patterns_for(repo, seeds, args.public_repo))
    text, findings = render(report, args.show_values)
    print(text)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
