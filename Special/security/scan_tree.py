"""Read-only working-tree scan; Python 3.11+, Git, stdout masked by default.

    python Special/security/scan_tree.py /path/to/repo --settings-home /path/to/profile --json

Common settings own saved policy; explicit --legacy-policy selects old text lists only when
no common settings file exists. --out explicitly creates a full private report; no implicit
report/log/config is written. See --help. Returns 0 checked, 1 findings, 2 incomplete/failure.
Optional --engine gitleaks/betterleaks/trufflehog may be repeated; --engine none overrides
saved selection. Engines are never installed automatically. Findings include masked location,
line, report-local id and remedy guidance; requested reports are presented as artifacts.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Special.security._cli import main

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main("tree"))
