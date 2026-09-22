"""Push one repository's current branch to its upstream. Never forced.

    python Basic/push.py <repo>

A push without `--force` is refused by git itself unless it is a fast-forward of the remote:
the mirror image of `pull --ff-only`. There is no parameter here that could add `--force`,
`--force-with-lease`, a `+refspec`, or `--mirror`, and there must never be one. Deciding
*whether* to push (ahead-only, clean, freshly re-checked) belongs to the caller.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import Result, run_git  # noqa: E402

EFFECT = "remote"

PUSH_TIMEOUT_SECONDS = 300


def push(repo: Path | str) -> Result:
    """`git push` of the current branch to its configured upstream. Never raises."""
    return run_git(repo, ["push"], timeout=PUSH_TIMEOUT_SECONDS)


def main(argv: list[str]) -> int:
    enable_unicode_output()
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    result = push(Path(argv[0]))
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
