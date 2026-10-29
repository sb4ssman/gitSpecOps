"""Push one repository's current branch to its upstream. Never forced.

    python Basic/push.py <repo>

A push without `--force` is refused by git itself unless it is a fast-forward of the remote:
the mirror image of `pull --ff-only`. There is no parameter here that could add `--force`,
`--force-with-lease`, a `+refspec`, or `--mirror`, and there must never be one. Deciding
*whether* to push (ahead-only, clean, freshly re-checked) belongs to the caller.
"""
from __future__ import annotations

import sys
import re
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


def push_snapshot(repo: Path | str, repository: str, tip: str, destination: str) -> Result:
    """Push exactly one full commit id to one branch, with normal fast-forward checks.

    The caller owns target selection, inspection and consent. An explicit repository endpoint
    and refspec prevent default ref mappings widening the operation. Tags and submodule
    publication are disabled for this invocation; hooks/auth remain Git's responsibility.
    The original push() and direct Basic script keep their existing behavior.
    """
    if (not isinstance(repository, str) or not repository or repository.startswith("-") or
            any(char in repository for char in "\0\r\n") or
            not isinstance(tip, str) or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", tip) is None or
            not isinstance(destination, str) or not destination.startswith("refs/heads/")):
        raise ValueError("a fixed commit, branch and repository endpoint are required")
    valid = run_git(repo, ["check-ref-format", destination])
    if valid.returncode:
        raise ValueError("invalid destination branch")
    return run_git(repo, ["push", "--no-follow-tags", "--no-mirror", "--recurse-submodules=no", "--",
                          repository, f"{tip}:{destination}"], timeout=PUSH_TIMEOUT_SECONDS)


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
