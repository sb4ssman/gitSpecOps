"""Configure and inspect unfinished-work snapshots that another machine can restore.

Why:          uncommitted work on a machine that dies is lost unless a copy waits elsewhere.
Reads:        the recovery settings and the snapshot store.
May change:   recovery settings; preview and restore act only in a disposable checkout.
Results:      text on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/recovery.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("recovery",))


EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
