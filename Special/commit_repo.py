"""secure-commit: check named files, message and identity, then commit only an approved plan.

Why:          a commit should never carry a secret or a private value by accident.
Reads:        the named files and the shared security policy.
May change:   once its plan is approved: one commit of the named files.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso secure-commit /path/to/repo file.txt -m "Describe the change"
    gitso secure-commit /path/to/repo file.txt -m "Describe the change" --apply PLAN_ID

Python 3.11+, Git 2.36+. Checking writes no index, Git objects, report or settings. Applying uses
named working-tree contents, preserves other staged work and runs existing traditional hooks
through a temporary per-command relay. Unreviewed hook changes hold the commit. No persistent
hook installation, automatic push or rollback. See --help for profile options.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Special._security._commit.cli import main

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
