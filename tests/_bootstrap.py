"""The single import-path bootstrap for every test, wherever it sits under `tests/`.

Each test used to carry its own hand-rolled `sys.path` incantation, in five different shapes,
each assuming a fixed depth below the repository root. Grouping the tests into subfolders broke
every one of them at once, which is exactly the kind of churn one shared helper prevents.

Paths are added **per area**, not all at once: the three tool folders are flat script
directories, so putting all of them on `sys.path` unconditionally would let a module in one tool
shadow a same-named module in another (`config.py` is the obvious candidate). A test asks for
what it actually imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC_DIR = ROOT / "git-sync-suggester"

AREAS = {
    "archive": [ROOT / "git-archive-updater"],
    "duplicator": [ROOT / "github-org-duplicator"],
    # Sync Suggester is itself split into folders; _paths.bootstrap() owns that list, so this
    # only needs the tool root where _paths.py lives.
    "sync": [SYNC_DIR],
}


def setup(*areas: str) -> Path:
    """Put the repo root (for `shared/`) plus each requested area on `sys.path`. Returns ROOT."""
    wanted = [ROOT]
    for area in areas:
        if area not in AREAS:
            raise ValueError(f"unknown test area {area!r}; expected one of {sorted(AREAS)}")
        wanted.extend(AREAS[area])
    for path in wanted:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    if "sync" in areas:
        # Sync tests import core/, fleet/ and app/ modules by bare name, same as the tool does.
        from _paths import bootstrap

        bootstrap()
    return ROOT
