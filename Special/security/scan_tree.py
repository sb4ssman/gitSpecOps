"""Read-only working-tree or staged-byte scan; Python 3.11+, Git, masked stdout.

    python Special/security/scan_tree.py /path/to/repo --settings-home /path/to/profile --json
    python Special/security/scan_tree.py /path/to/repo --staged --out /private/staged.json

Common settings own saved policy; explicit --legacy-policy selects old text lists only when
no common settings file exists. --out explicitly creates a full private report; no implicit
report/log/config is written. See --help. Returns 0 checked, 1 findings, 2 incomplete/failure.
Optional --engine gitleaks/betterleaks/trufflehog may be repeated; --engine none overrides
saved selection. Engines are never installed automatically. Findings include masked location,
line, report-local id and remedy guidance; requested reports are presented as artifacts.
Full reports may use external private storage; inside Git they must be ignored/untracked.
Scoped accepted examples remain visible. review_finding.py previews/saves/revokes decisions;
changed content and coverage gaps still hold actions. No source or Git state is changed here.
--staged reads changed-file bytes from the index instead of working/untracked files. It never
stages, commits or invokes clean filters; use it to review the bytes produced by Git's staging.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Special.security._cli import main

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main("tree"))
