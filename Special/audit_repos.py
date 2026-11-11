"""Audit this machine's repositories: missing remotes, unfinished work, oddities.

Why:          the repositories with no origin are exactly the ones an inventory forgets.
Reads:        every repository under the saved or given roots.
May change:   nothing.
Results:      a report on stdout, or --json; exit 1 when something needs a look.
Layer:        Special: this machine, once.
Status:       working

    python Special/audit_repos.py --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.commands import audit_repos_main as main  # noqa: E402

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
