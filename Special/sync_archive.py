"""Plan archives or explicitly update, sync, repair or publish them.

Why:          an archive should match what its host says should be there.
Reads:        the archive's checkouts and the host's repository list (through gh).
May change:   with the chosen action: clones, fast-forwards, origin repairs; with --publish, checked non-forced pushes.
Results:      a plan or result on stdout, or JSON; reports and logs as settings choose.
Layer:        Special: this machine, once.
Status:       working

    python Special/sync_archive.py --help
    python Special/sync_archive.py --root /path/to/archive --json --no-log
    python Special/sync_archive.py --root /path/to/archive --sync --yes

Default use plans to stdout; saved output/log preferences and explicit flags select channels.
Publication is a separate action: exact planned tips/targets pass outgoing-history security
checks before any non-force push. Masked findings are included in the shared result.
--dry-run never approves security. No registration, enrollment or setup is implied.
Import run_archives for headless use with explicit settings, requests and approval callback.
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
