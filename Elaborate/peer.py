"""Run this machine's fleet peer headless: observe, publish, talk to peers, over time.

Why:          the fleet only knows what running peers tell it.
Reads:        the observed repositories, peers' published status, the tailnet when it is up.
May change:   nothing in your repositories; writes its own state and manifests. Catch-up runs only
              where a standing consent allows it. `rescan` asks a running peer for one inventory.
Results:      while running, log lines on stdout; errors as JSON without a terminal. The web view and tray: gitso serve-web, gitso tray.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/peer.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("run", "rescan"))


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
