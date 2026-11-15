"""List unsaved VS Code buffers that belong to this machine's repositories.

Why:          work typed but never saved is invisible to Git; this shows where it is.
Reads:        VS Code's local hot-exit backup headers (metadata, never content).
May change:   nothing.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso machine buffers --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import list_live_buffers_main as main  # noqa: E402

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
