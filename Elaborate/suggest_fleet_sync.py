"""Suggest sync across the fleet from every machine's published status.

Why:          which copies are ahead, behind or missing is a question no single machine can answer.
Reads:        published manifests from the configured transport; the local catalog for names.
May change:   nothing.
Results:      the fleet table on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/suggest_fleet_sync.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import status  # noqa: E402


def main(argv=None):
    return status(argv, ("dashboard",))


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
