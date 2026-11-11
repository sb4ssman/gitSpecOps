"""Clone this machine's observed working set into another library folder.

Why:          rebuilding a library on a new disk or machine from what this one has.
Reads:        the observed repositories and their origins.
May change:   with --apply --yes: clones into the existing --destination folder; nothing else.
Results:      the plan, then the results, on stdout.
Layer:        Special: this machine, once.
Status:       working

    python Special/materialize.py --help
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
