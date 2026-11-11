"""Report repositories other machines have that this machine does not.

Why:          a fleet converges only when each machine knows what it is missing.
Reads:        published manifests; the local catalog.
May change:   the local catalog's names, unless --no-record.
Results:      a report on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/converge.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import status  # noqa: E402


def main(argv=None):
    return status(argv, ("converge",))


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
