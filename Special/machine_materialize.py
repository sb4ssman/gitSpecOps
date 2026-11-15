"""Clone this machine's observed working set into another library folder.

Why:          rebuilding a library on a new disk or machine from what this one has.
Reads:        the observed repositories and their origins.
May change:   once its plan is approved: clones into the existing --destination folder; nothing else.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso machine materialize --destination /new/library                   (shows the plan)
    gitso machine materialize --destination /new/library --apply PLAN_ID   (clones exactly that plan)
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import materialize_main as main  # noqa: E402

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
