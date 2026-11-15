"""secure-push: plan one branch push, and check its outgoing history before publishing.

Why:          publishing should check the outgoing history first, every time.
Reads:        the branch, its outgoing commits and the shared security policy.
May change:   once its plan is approved: one non-forced push of exactly the planned tip.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso secure-push /path/to/repo
    gitso secure-push /path/to/repo --apply PLAN_ID

Python 3.11+ and Git; --settings-home selects a profile. The plan reads only local scope and
policy, writes no files and is no security clearance. Applying needs the unchanged plan,
fetches the selected remote and uses the same security gate as sync-archive. One matching
upstream on an existing remote branch. No force, extra tags, other branches, hooks or commits.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Special._security._push_cli import main

EFFECT = "remote"

if __name__ == "__main__":
    raise SystemExit(main())
