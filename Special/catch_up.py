"""Fetch this machine's observed repositories and fast-forward the safe ones.

Why:          behind-only checkouts are the one change that is always safe to make for you.
Reads:        the observed repositories (saved roots and baskets, or --root).
May change:   with --apply --yes: fast-forward of clean, behind-only checkouts. Fetch updates
              remote-tracking refs only. Never commits, merges, rebases or resets.
Results:      the plan, then the results, on stdout.
Layer:        Special: this machine, once.
Status:       working

    python Special/catch_up.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import catch_up_main as main  # noqa: E402

EFFECT = "local"

if __name__ == "__main__":
    raise SystemExit(main())
