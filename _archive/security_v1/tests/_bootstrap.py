"""Import path for the archived suite's own test: the archive first, so its frozen copies of
`Basic/` and `_os/` are the ones imported -- never the live layers, which keep changing."""
from __future__ import annotations

import sys
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1]
#: The gitSpecOps checkout: where the reports' ignored output folder lives.
ROOT = ARCHIVE.parents[1]


def setup(*_areas: str) -> Path:
    if str(ARCHIVE) not in sys.path:
        sys.path.insert(0, str(ARCHIVE))
    return ROOT
