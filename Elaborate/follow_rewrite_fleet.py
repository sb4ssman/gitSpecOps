"""Ask the fleet's other machines to follow a rewritten history.

Why:          after a history cleanup every clone, on every machine, must move to the new history.
Reads:        the cleanup's commit map; the fleet.
May change:   nothing yet.
Results:      nothing yet.
Layer:        Elaborate: other machines, or over time.
Status:       placeholder: needs the attended remote-request protocol (Elaborate/request.py).

    python Elaborate/follow_rewrite_fleet.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import placeholder  # noqa: E402


def main(argv=None):
    return placeholder("follow_rewrite_fleet", "run Special/follow_rewrite.py on each machine")


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
