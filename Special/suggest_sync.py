"""Suggest what each of this machine's repositories needs: commit, push, pull, or nothing.

Why:          the one-glance answer to "what needs attention here?" without any fleet.
Reads:        Git facts of the repositories under the saved or given roots; working files and cached
              outgoing history for the shared security advice.
May change:   nothing in your repositories. --fetch updates remote-tracking refs only. The local-only
              catalog (names for repository ids) is updated unless --no-catalog.
Results:      a table and security advice on stdout, or --json. Nothing is published.
Layer:        Special: this machine, once.
Status:       working

    python Special/suggest_sync.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import suggest_sync_main as main  # noqa: E402

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
