"""Shared scan command interface. Findings go to stdout masked; full reports are explicit."""
from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path

from Basic._run import CommandFailed
from Special._runtime.files import excluded
from Special._settings import SECURITY_ENGINES, SettingsError
from Special.security._findings import write_report
from Special.security._material import scan
from Special.security._me import load_policy


def main(material, argv=None):
    description = ("Inspect indexed and non-ignored untracked working-tree files; does not scan staged-only bytes."
                   if material == "tree" else
                   "Inspect history reachable from every local ref and HEAD; no fetch, reflogs or unreachable objects.")
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("repo", type=Path)
    if material == "tree":
        parser.add_argument("--staged", action="store_true", help="Inspect staged changed-file bytes instead of working/untracked files; no staging or commit.")
    parser.add_argument("--settings-home", type=Path, help="selected user-data profile; no creation or migration")
    parser.add_argument("--legacy-policy", action="store_true",
                        help="explicitly read legacy text policy; refuses any existing common settings file")
    parser.add_argument("--out", type=Path, help="exclusive-create a full private JSON report; inside Git it must be ignored/untracked")
    parser.add_argument("--json", action="store_true", help="masked JSON on stdout")
    parser.add_argument("--engine", action="append", choices=("none", *SECURITY_ENGINES),
                        help="optional engine; repeat to combine, or none to override saved engines; no installation")
    parser.add_argument("--never-publish", type=Path, help="additional protected values (legacy: selected watch file); absence is incomplete")
    parser.add_argument("--safe-file", type=Path, help="additional safe values (legacy: selected safe file); absence is incomplete")
    parser.add_argument("--safe", action="append", default=[], metavar="VALUE")
    parser.add_argument("--public-login", action="append", default=[], metavar="HANDLE")
    if material == "history":
        parser.add_argument("--ref", action="append", help="existing full ref name or HEAD; repeatable (default: all local refs)")
    args = parser.parse_args(argv)
    if material == "tree" and args.staged:
        material = "index"
    if args.engine and "none" in args.engine and len(args.engine) != 1:
        parser.error("select none alone, or select engines without none")
    try:
        policy = load_policy(args.repo, never_file=args.never_publish, safe_file=args.safe_file,
                             safe=args.safe, login=args.public_login, home=args.settings_home,
                             legacy_policy=args.legacy_policy)
        if args.out is not None and excluded(Path(os.path.abspath(args.out.expanduser())), policy.exclude_paths):
            raise SettingsError("requested report destination is excluded; no scan was started")
        options = {} if args.engine is None else {"engines": [] if args.engine == ["none"] else args.engine}
        report = scan(args.repo, policy, material=material, refs=getattr(args, "ref", None), **options)
        if args.out is not None:
            write_report(args.out, report)
    except (CommandFailed, OSError, ValueError) as exc:
        # Paths and subprocess stderr may contain the very values being protected.
        message = str(exc) if isinstance(exc, SettingsError) else "Scan or report failed; no clean result issued."
        if args.json:
            print(json.dumps({"status": "error", "coverage": "incomplete", "error_type": type(exc).__name__,
                              "message": message}))
        else:
            print(message, file=sys.stderr)
        return 2
    print(json.dumps(report.record(), indent=2) if args.json else report.summary())
    return report.exit_code
