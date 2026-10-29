"""CLI adapter for the callable checked push; local planning never implies security clearance.

Preview prints a content-bound plan id. Apply needs that id and checks actual outgoing history
before publishing. Only masked checking and finite errors reach stdout; no reports/logs saved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from Special.security._push import push_checked


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plan one branch push, then check outgoing history before publishing.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--settings-home", type=Path)
    parser.add_argument("--legacy-policy", action="store_true")
    parser.add_argument("--json", action="store_true", help="masked structured result")
    parser.add_argument("--apply", action="store_true", help="fetch/check/push only the approved current plan")
    parser.add_argument("--approve", help="exact plan id from the local preview")
    args = parser.parse_args(argv)
    if args.approve is not None and not args.apply:
        parser.error("--approve requires --apply")
    result = push_checked(args.repo, settings_home=args.settings_home, legacy_policy=args.legacy_policy,
                          apply=args.apply, approve=args.approve)
    if args.json:
        print(json.dumps(result.record(), indent=2))
    else:
        if result.report is not None:
            print(result.report.summary())
        print(result.message)
        if result.plan_id is not None:
            print("Plan: " + result.plan_id)
    return 0 if result.status in ("planned", "pushed", "already-current") else (
        1 if result.status in ("blocked", "review-required") else 2)
