"""Runtime for Git's native hooks. This never creates a commit or sends a push."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from Basic._facts import next_commit_identity
from Special._security._material import scan
from Special._security._me import load_policy

EVENTS = ("pre-commit", "prepare-commit-msg", "commit-msg", "pre-merge-commit",
          "applypatch-msg", "pre-applypatch", "pre-push")
MODES = ("scan", "local-only", "off")
STATE = "gitso-commit-policy.json"


def main(argv=None):
    state, event, *arguments = sys.argv[1:] if argv is None else argv
    repo = Path.cwd()
    try:
        policy_record = json.loads(Path(state).read_text(encoding="utf-8"))
        mode = policy_record["mode"]
        if mode not in MODES or event not in EVENTS:
            raise ValueError("invalid gate request")
        if mode == "off":
            return 0
        if mode == "local-only":
            print("Git operation blocked by gitso: this checkout is local-only.", file=sys.stderr)
            return 1
        if event not in ("commit-msg", "applypatch-msg", "pre-applypatch"):
            return 0
        print("gitso security: checking proposed commit.", file=sys.stderr, flush=True)
        policy = load_policy(repo, home=Path(policy_record["home"]))
        if event == "pre-applypatch":
            report = scan(repo, policy, material="index")
        else:
            with Path(arguments[0]).open("rb") as message_file:
                raw = message_file.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("message too large")
            proposal = {"files": (), "message": raw.decode("utf-8"),
                        "identities": next_commit_identity(repo)}
            if event == "applypatch-msg":
                report = scan(repo, policy, material="proposed", proposal=proposal)
            else:
                report = scan(repo, policy, material="index", proposal=proposal)
        if report.check_status == "passed":
            print("gitso security: passed.", file=sys.stderr)
            return 0
        print(f"gitso security: blocked ({len(report.actionable)} finding(s), "
              f"{len(report.gaps)} coverage gap(s)).", file=sys.stderr)
    except (IndexError, KeyError, OSError, TypeError, ValueError, RuntimeError):
        print("gitso security: blocked because checking could not finish.", file=sys.stderr)
    return 1
