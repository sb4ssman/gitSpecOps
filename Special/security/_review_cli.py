"""CLI adapter for one scoped example review; masked output and exact-plan approval.

Preview reads a full private report and writes nothing. --apply --approve PLAN_ID saves one
private immutable decision; --revoke REVIEW_ID previews its revocation. No raw reason/value
is printed, no settings are edited and no Git action is performed.
"""
import argparse
import json
from pathlib import Path

from Special.security._review_operation import review_finding


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview and explicitly save/revoke a content-bound example review.")
    parser.add_argument("report", type=Path, help="Full private report created by scan-tree/scan-history --out.")
    parser.add_argument("finding", nargs="?", help="Report-local finding id; selects scope, never authorizes a save.")
    parser.add_argument("--revoke", help="Revoke one active review id instead of accepting a finding.")
    parser.add_argument("--reason", required=True, help="Private explanation; never echoed to normal output.")
    parser.add_argument("--settings-home", type=Path)
    parser.add_argument("--legacy-policy", action="store_true", help="Explicitly read existing text policy without conversion.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", help="Exact current review-plan id from preview.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.finding) == bool(args.revoke):
        parser.error("select a finding or --revoke, not both")
    if args.approve is not None and not args.apply:
        parser.error("--approve requires --apply")
    result = review_finding(args.report, args.finding, args.reason, home=args.settings_home,
                            legacy_policy=args.legacy_policy, apply=args.apply,
                            approve=args.approve, revoke=args.revoke)
    if args.json:
        print(json.dumps(result.record(), indent=2))
    else:
        print(result.message)
        if result.scope:
            scope = result.scope
            print(f"{scope['finding_id']} [{scope['severity']}] {scope['check']} at {scope['where']}:{scope['line']}: {scope['value']}")
        if result.plan_id:
            print("Plan: " + result.plan_id)
        if result.review_id:
            print("Review: " + result.review_id)
        for artifact in result.artifacts:
            print(f"Produced {artifact['kind']}: {artifact['path']} ({artifact['disclosure']})")
    return 0 if result.status in ("planned", "accepted", "revoked", "already-reviewed") else 2
