"""Preview/check and explicitly commit named files using shared security policy.

    python Special/commit_repo.py /path/to/repo file.txt -m "Describe the change" --json
    python Special/commit_repo.py /path/to/repo file.txt -m "Describe the change" --apply --approve PLAN_ID

Python 3.11+, Git 2.36+. Preview writes no index, Git objects, report or settings. Apply uses
named working-tree contents, preserves other staged work and delegates existing traditional
hooks through a temporary per-command relay. Unreviewed hook changes hold the commit. No
persistent hook installation, automatic push or rollback. Source/metadata checks are optimistic
against other writers; unsupported Git states fail explicitly. See --help for profile options.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Special.security._commit.cli import main

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
