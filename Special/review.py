"""Review one exact example finding without allowing its value everywhere.

Why:          an example value that is fine in one exact place should not hold every action forever.
Reads:        a private scan report.
May change:   once its plan is approved: one saved review decision in the profile.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso review /private/scan.json finding-000001 --reason "Reviewed test example"
    gitso review /private/scan.json finding-000001 --reason "..." --apply PLAN_ID

The plan creates no state. Use --revoke REVIEW_ID instead of a finding to revoke a review.
Changed content, check or location needs review again. Prohibited values, strong credentials
and coverage gaps cannot be waived. No Git action is performed. Values are always masked; the
reason is never printed (an apply command shows it as a placeholder).
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._security._review_cli import main

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
