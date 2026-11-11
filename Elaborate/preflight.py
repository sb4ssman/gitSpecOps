"""Check what fleet setup can use on this machine: Git, GitHub, Tailscale, a port, sync folders.

Why:          setup should offer only what will work.
Reads:        tool availability and local folders.
May change:   nothing.
Results:      text on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/preflight.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("preflight",))


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
