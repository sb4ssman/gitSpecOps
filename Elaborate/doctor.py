"""Show this machine's fleet configuration and which peers answer; hides the key.

Why:          the first question when the fleet looks wrong is what this machine thinks it is.
Reads:        the fleet configuration; peers on the tailnet.
May change:   nothing.
Results:      text on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/doctor.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("doctor",))


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
