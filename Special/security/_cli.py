"""Shared scan command interface. Findings go to stdout masked; full reports are explicit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from Basic._run import CommandFailed
from Special.security._findings import write_report
from Special.security._material import scan
from Special.security._me import load_policy


def main(material, argv=None):
    description = ("Inspect indexed and non-ignored untracked working-tree files; does not scan staged-only bytes."
                   if material == "tree" else
                   "Inspect history reachable from every local ref and HEAD; no fetch, reflogs or unreachable objects.")
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--out", type=Path, help="exclusive-create a full private JSON report in a Git-ignored location")
    parser.add_argument("--json", action="store_true", help="masked JSON on stdout")
    parser.add_argument("--never-publish", type=Path, help="explicit watch-list file; absence makes coverage incomplete")
    parser.add_argument("--safe-file", type=Path, help="explicit safe-list file; absence makes coverage incomplete")
    parser.add_argument("--safe", action="append", default=[], metavar="VALUE")
    parser.add_argument("--public-login", action="append", default=[], metavar="HANDLE")
    if material == "history":
        parser.add_argument("--ref", action="append", help="existing full ref name or HEAD; repeatable (default: all local refs)")
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.repo, never_file=args.never_publish, safe_file=args.safe_file,
                             safe=args.safe, login=args.public_login)
        report = scan(args.repo, policy, material=material, refs=getattr(args, "ref", None))
        if args.out is not None:
            write_report(args.out, report)
    except (CommandFailed, OSError, ValueError) as exc:
        # Paths and subprocess stderr may contain the very values being protected.
        print(f"Scan/report failed ({type(exc).__name__}); no clean result issued.")
        return 2
    print(json.dumps(report.record(), indent=2) if args.json else report.summary())
    return report.exit_code
