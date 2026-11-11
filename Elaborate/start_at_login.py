"""Inspect or change whether the gitSpecOps tray starts when you log in.

Why:          a fleet whose peers are not running knows nothing.
Reads:        this user's login items.
May change:   this user's login items only (never system-wide).
Results:      JSON on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/start_at_login.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("autostart",))


EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
