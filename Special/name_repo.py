"""Give a repository id a readable name in this machine's local-only catalog.

Why:          fleet rows for repositories never cloned here would otherwise show only an id.
Reads:        the local catalog.
May change:   the local catalog only.
Results:      the new name, or the catalog listing.
Layer:        Special: this machine, once.
Status:       working

    python Special/name_repo.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import name_repo_main as main  # noqa: E402

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
