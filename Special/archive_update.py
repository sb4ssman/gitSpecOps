"""Fast-forward the eligible repositories in folders of clones; shows the plan first.

Why:          reference collections fall behind; only safe fast-forwards should catch them up.
Reads:        the folders' checkouts.
May change:   once a folder's plan is approved: fast-forward of clean, eligible checkouts.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso archive update --root /path/to/archive                   (shows the plan)
    gitso archive update --root /path/to/archive --apply PLAN_ID

It never clones missing repositories (archive sync --sync does). --save-report also saves the
run's report as a JSON file; the counts-only log is on unless --no-log. Importing does nothing.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._archive.update_cli import main

EFFECT = "local"

from Special._archive.update_operation import UpdateRequest, UpdateResult, run_update, render_result

if __name__ == "__main__":
    raise SystemExit(main())
