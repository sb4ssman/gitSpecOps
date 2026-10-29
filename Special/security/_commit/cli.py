"""Direct/launcher CLI over commit_checked; preview by default, exact approval for apply.

Help performs no configuration reads. Public output is always the safe structured result or
its matching text summary; native hook/Git output stays in the private backend result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from Special.security._commit.operation import commit_checked


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check named working-tree files, message and identity before committing.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("paths", nargs="+", help="literal repo-relative files or tracked deletions, not directories")
    parser.add_argument("-m", "--message", required=True)
    parser.add_argument("--settings-home", type=Path)
    parser.add_argument("--legacy-policy", action="store_true")
    parser.add_argument("--json", action="store_true", help="masked result only; native hook output is not disclosed")
    parser.add_argument("--apply", action="store_true", help="commit only after current plan matches --approve")
    parser.add_argument("--approve", help="exact plan id from a prior checked preview")
    args = parser.parse_args(argv)
    if args.approve is not None and not args.apply:
        parser.error("--approve requires --apply")
    result = commit_checked(args.repo, args.paths, args.message, settings_home=args.settings_home,
                           legacy_policy=args.legacy_policy, apply=args.apply, approve=args.approve)
    print(json.dumps(result.record(), indent=2) if args.json else result.summary())
    if result.status in ("ready", "committed", "nothing-to-commit"):
        return 0
    return 1 if result.status in ("blocked", "review-required", "hook-rejected") else 2
