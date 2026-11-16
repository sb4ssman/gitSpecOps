"""This machine's libraries as a folder map, each repository's state on its line.

Why:          see the whole library at a glance: folders, repositories and what each one needs.
Reads:        Git status of the repositories under the library folders; Orbital-Workshop's folder
              mapper when present (--mapper, or found inside a library).
May change:   nothing.
Results:      JSON without a terminal (or with --json); a screen at one. Nothing is published.
Layer:        Special: this machine, once.
Status:       working

    gitso machine map --help
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._sync.folder_map import folder_map_main as main  # noqa: E402

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main())
