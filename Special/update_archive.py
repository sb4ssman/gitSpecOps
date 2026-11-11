"""Fast-forward eligible existing repositories in one or more local archives.

Why:          reference collections fall behind; only safe fast-forwards should catch them up.
Reads:        the archive's checkouts.
May change:   without --scan-only: fast-forward of clean, eligible checkouts.
Results:      a result on stdout, or --json; reports and logs as settings choose.
Layer:        Special: this machine, once.
Status:       working

    python Special/update_archive.py --help
    python Special/update_archive.py --root /path/to/archive --scan-only

Without --scan-only this updates clean eligible checkouts. It does not clone missing repos.
Saved roots/output/logging preferences are optional. --json gives a machine-readable result;
--no-report forces stdout only and --no-log disables operational logging. Reports are off by
default; local counts-only logs default on. Importing performs no operation.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._archive.update_cli import main

EFFECT = "local"

from Special._archive.update_operation import UpdateRequest, UpdateResult, run_update, render_result

if __name__ == "__main__":
    raise SystemExit(main())
