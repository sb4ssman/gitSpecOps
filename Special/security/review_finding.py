"""Review one exact example finding without globally allowing its value.

    python Special/security/review_finding.py --help
    python Special/security/review_finding.py /private/scan.json finding-000001 --reason "Reviewed test example"

Preview creates no state. Rerun with --apply --approve REVIEW_PLAN_ID to save exactly that
decision under the selected user-data home. Use --revoke REVIEW_ID instead of a finding to
preview/revoke acceptance. Changed content/check/location needs review again. Prohibited
values, strong credentials and coverage gaps cannot be waived. No Git action is performed.
Default text and --json always mask values; full evidence/reasons remain in private files.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special.security._review_cli import main
from Special.security._review_operation import ReviewResult, review_finding

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
