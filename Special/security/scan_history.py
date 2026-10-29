"""Read-only local reachable-history scan; Python 3.11+, Git, no fetch or rewrite.

    python Special/security/scan_history.py /path/to/repo --settings-home /path/to/profile --json

Common settings own saved policy; --legacy-policy explicitly selects old text lists without
a common profile. Masked stdout is default; --out requests a full private report. --ref narrows
local reachable refs. No implicit report/log/config. Returns 0 checked, 1 findings, 2 incomplete.
Optional --engine gitleaks/betterleaks/trufflehog may be repeated; --engine none overrides
saved selection. Only already selected material is sent to an engine, without provider
verification. Masked actionable records and explicit report artifacts share the tree contract.
Full reports may use external private storage; inside Git they must be ignored/untracked.
Scoped reviews match exact finding content/location; they never clear uninspected material.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Special.security._cli import main

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main("history"))
