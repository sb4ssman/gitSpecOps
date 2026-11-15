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

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Temporary folders in their resolved form. A test compares a path it made with the same path
# after the code resolved it; on a CI runner the temp folder is a Windows short name
# (C:\Users\<user>~1\...) and on macOS it sits behind the /var -> /private/var link, so the two
# spellings of one folder would differ. Children the tests start inherit the same folder.
_TEMP = os.path.realpath(tempfile.gettempdir())
tempfile.tempdir = _TEMP
for _name in ("TMPDIR", "TEMP", "TMP"):
    os.environ[_name] = _TEMP

AREAS = {
}


def setup(*areas: str) -> Path:
    """Put the repo root (for the layers) plus each requested area on `sys.path`. Returns ROOT."""
    wanted = [ROOT]
    for area in areas:
        if area not in AREAS:
            raise ValueError(f"unknown test area {area!r}; expected one of {sorted(AREAS)}")
        wanted.extend(AREAS[area])
    for path in wanted:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    return ROOT
