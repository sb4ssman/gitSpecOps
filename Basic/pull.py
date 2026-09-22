"""Fast-forward one repository to its upstream. Never merges, never rebases.

    python Basic/pull.py <repo>

`--ff-only` is the whole safety argument: a fast-forward cannot destroy data and never asks
for a choice, so when git cannot fast-forward it refuses, and the refusal is reported as a
failure for a human -- never resolved here. There is no option to do anything else.
Callers decide *whether* a repository qualifies (clean, behind-only); this only performs it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import run_git  # noqa: E402

EFFECT = "local"

UPDATED = "updated"
ALREADY_CURRENT = "already current"


def fast_forward(repo: Path | str, remote: str = "origin") -> str:
    """Fetch, then `pull --ff-only`. Returns "updated", "already current", or "failed: ..."."""
    fetched = run_git(repo, ["fetch", remote])
    if fetched.returncode != 0:
        return f"failed: fetch: {fetched.stderr.strip() or 'error'}"
    pulled = run_git(repo, ["pull", "--ff-only"])
    if pulled.returncode != 0:
        return f"failed: pull --ff-only: {pulled.stderr.strip() or 'not a fast-forward'}"
    combined = f"{pulled.stdout}\n{pulled.stderr}".lower()
    return ALREADY_CURRENT if ("up to date" in combined or "up-to-date" in combined) else UPDATED


def main(argv: list[str]) -> int:
    enable_unicode_output()
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    result = fast_forward(Path(argv[0]))
    print(result)
    return 1 if result.startswith("failed:") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
