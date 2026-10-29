"""Plan archives or explicitly update, sync, repair or publish them.

    python Special/archive_sync.py --help
    python Special/archive_sync.py --root /path/to/archive --json --no-log
    python Special/archive_sync.py --root /path/to/archive --sync --yes

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
