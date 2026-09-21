"""Report one repository's facts as JSON. Read-only.

    python Basic/status.py <repo-path>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._facts import repo_facts  # noqa: E402

EFFECT = "none"


def main(argv: list[str]) -> int:
    enable_unicode_output()
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    path = Path(argv[0])
    if not path.is_dir():
        print(f"Not a directory: {path}", file=sys.stderr)
        return 2
    print(json.dumps(repo_facts(path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
