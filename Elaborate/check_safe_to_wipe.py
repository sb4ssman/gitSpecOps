"""Report whether this machine could be wiped without losing work.

Why:          unknown is never an all-clear: work must exist on a remote or in a recovery snapshot.
Reads:        every repository under the configured roots, freshly fetched; recovery snapshots.
May change:   nothing in your repositories (fetch updates remote-tracking refs only).
Results:      a report on stdout; exit 1 unless safe.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/check_safe_to_wipe.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("safe-to-wipe",))


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
