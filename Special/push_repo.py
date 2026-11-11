"""Plan a single branch push and check its outgoing history before publishing.

Why:          publishing should check the outgoing history first, every time.
Reads:        the branch, its outgoing commits and the shared security policy.
May change:   with --apply and the plan id: one non-forced push of exactly the planned tip.
Results:      a masked plan and result on stdout, or --json.
Layer:        Special: this machine, once.
Status:       working

    python Special/push_repo.py /path/to/repo --json
    python Special/push_repo.py /path/to/repo --apply --approve PLAN_ID

Python 3.11+ and Git; --settings-home selects a profile, --legacy-policy is explicit. Preview
reads only local scope/policy, writes no files and provides no outgoing security clearance.
Apply needs the unchanged plan, fetches the selected remote and uses the same security gate as
Archive Sync. Supports one matching upstream/push destination on an existing remote branch.
No force, extra tags, other branches, hook installation or automatic commit. Masked output to
stdout, no report/log unless a later common output integration explicitly requests one.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Special._security._push_cli import main

EFFECT = "remote"

if __name__ == "__main__":
    raise SystemExit(main())
