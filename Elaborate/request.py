"""Attended remote requests: one machine asks another to act, a person approves the plan.

Why:          "B, commit this and push" from machine A, without a shell on B.
Reads:        the asking machine's request; the acting machine's own plan.
May change:   nothing yet.
Results:      nothing yet.
Layer:        Elaborate: other machines, or over time.
Status:       placeholder: protocol designed (knowledge/architecture-layers.md), not built.

    python Elaborate/request.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Elaborate._fleet.commands import placeholder  # noqa: E402


def main(argv=None):
    return placeholder("request", "the attended remote-request protocol")


EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
