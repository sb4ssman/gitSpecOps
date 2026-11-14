"""Copy GitHub repositories with explicit mode, scope and confirmation.

Why:          copying a whole GitHub organization by hand is slow and easy to get wrong.
Reads:        the chosen GitHub namespaces (through gh) and local folders.
May change:   local clones; in upload or migration modes, GitHub repositories, after confirmation.
Results:      JSON without a terminal (or with --json); a screen at one. Resume state in its runs folder.
Layer:        Special: this machine, once.
Status:       working

    gitso org copy --help
    gitso org copy
    gitso org copy --batch --namespaces all --dest /path/to/library

The menu offers download, upload, migration, batch download and single-repository download.
Git and authenticated gh are required for operations. Importing performs no operation.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._org_duplicator.command import cli_main

EFFECT = "remote"

if __name__ == "__main__":
    cli_main()
