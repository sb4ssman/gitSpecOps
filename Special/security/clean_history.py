"""DANGEROUS HISTORY MAINTENANCE: explicit cleanup into a new private mirror, never publish.

    python Special/security/clean_history.py plan /private/history.json --choices /private/choices.json --plan-out /private/plan.json --json
    python Special/security/clean_history.py apply /private/plan.json --workspace /private/new-run --approve PLAN_ID

First use scan-history --out for a full private report. Planning rescans and rejects stale
refs/findings. --include-remote-refs explicitly preserves remote-only history and origin/HEAD;
without it an ordinary checkout with tracking refs is refused. No fetch or settings change.
Application requires an attended terminal and typed REWRITE, with no --yes/confirmation flag.
GUI/callable clients use the same run_cleanup function after their own human approval.

The choice document has schema_version=1 and four required lists:
replace_findings: {finding_id, new, targets: [blob,path,message], ignore_case: bool, bounded: bool}.
remove_files: finding ids selecting the WHOLE containing file/container across history.
remove_paths: literal Git paths; a trailing slash explicitly selects the directory subtree.
rewrite_identities: {finding_id, name, email}, mapping the exact selected identity pair only.
Empty lists mean no choices of that kind. Never infer purge scope from a finding or missing file.
For example (substitute an actual content-finding id from your private report):

    {"schema_version": 1,
     "replace_findings": [{"finding_id": "finding-000007", "new": "public-example",
       "targets": ["blob", "path", "message"], "ignore_case": true, "bounded": true}],
     "remove_files": [], "remove_paths": [], "rewrite_identities": []}

No raw secret is needed in the choice file. Plans/native diagnostics/full rescans stay private;
stdout and optional common reports/logs are masked/counts-only. Missing/bad settings never fall
back. Every produced artifact is presented. A verified mirror grants no publication clearance
and does not rotate credentials, fix other clones or erase external copies. Review before use.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Special.security._cleanup_cli import main

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
