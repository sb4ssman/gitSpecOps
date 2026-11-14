"""Plan, then apply, updates, clones, repairs or publication for folders of clones.

Why:          an archive should match what its host says should be there.
Reads:        the archive's checkouts and the host's repository list (through gh).
May change:   once each plan is approved: clones, fast-forwards, origin repairs; with
              --publish, checked non-forced pushes.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working

    gitso archive sync --root /path/to/archive                     (inspects only)
    gitso archive sync --root /path/to/archive --sync              (plans; at a terminal, asks)
    gitso archive sync --root /path/to/archive --sync --apply PLAN_ID

Each folder's plan has its own id; repeat --apply for several. Publication is separate:
exact planned tips pass outgoing-history security checks before any non-forced push. An
approved plan is no security clearance. Import run_archives for headless use.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._archive.sync_cli import main
from Special._archive.operation import ArchiveResult, run_archives

EFFECT = "remote"

if __name__ == "__main__":
    raise SystemExit(main())
