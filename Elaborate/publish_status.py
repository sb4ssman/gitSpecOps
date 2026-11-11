"""Publish this machine's repository status for the fleet, and show it.

Why:          other machines can only suggest sync from status this machine has shared.
Reads:        the repositories under the saved roots; the configured transport (a synced folder or a
              private GitHub state repository).
May change:   the transport's copy of this machine's manifest (status facts and salted ids only).
              `init` saves settings and may create the private state repository.
Results:      a table on stdout, or --json.
Layer:        Elaborate: other machines, or over time.
Status:       working

    python Elaborate/publish_status.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import status  # noqa: E402


def main(argv=None):
    return status(argv, ("check", "init", "fleet-key", "doctor", "version"))


EFFECT = "remote"

if __name__ == "__main__":
    raise SystemExit(main())
