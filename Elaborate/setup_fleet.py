"""Enroll this machine in the fleet, or change its fleet settings.

Why:          joining the fleet is what lets machines see each other.
Reads:        the common settings profile, or the legacy fleet configuration.
May change:   this machine's fleet settings; `transports` may create a private GitHub state repository;
              `peer` without --configure-only also starts the peer.
Results:      messages on stdout.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/setup_fleet.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import fleet  # noqa: E402


def main(argv=None):
    return fleet(argv, ("setup", "peer", "convert", "transports", "baskets", "git-client",
                        "fleet-key"))


EFFECT = "remote"

if __name__ == "__main__":
    raise SystemExit(main())
