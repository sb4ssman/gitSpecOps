"""Push one repository's current branch to its upstream. Never forced.

Why:          publishing must never overwrite what is on the remote.
Reads:        the current branch and its upstream.
May change:   the remote branch, by fast-forward only; never forced.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Basic: one Git or host operation.
Status:       working

    gitso push <repo>

A push without `--force` is refused by git itself unless it is a fast-forward of the remote:
the mirror image of `pull --ff-only`. There is no parameter here that could add `--force`,
`--force-with-lease`, a `+refspec`, or `--mirror`, and there must never be one. Deciding
*whether* to push (ahead-only, clean, freshly re-checked) belongs to the caller.

The promise is enforced, not left to Git's configuration (an outside review, 2026-11-17): a bare
`git push` lets a configured push refspec (`+refs/...`), a mirror remote or `push.default`
decide what leaves. This names the upstream remote and one plain refspec (this commit to the
branch it tracks), and switches off mirror, tags and submodule pushes for the call.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic import _cli  # noqa: E402
from Basic._facts import upstream_of  # noqa: E402
from Basic._run import Result, run_git  # noqa: E402

EFFECT = "remote"

PUSH_TIMEOUT_SECONDS = 300


def push(repo: Path | str) -> Result:
    """Push the checked-out commit to the branch it tracks, and nothing else. Never raises.

    The remote and the refspec are explicit, so no configuration can widen it or overwrite the
    remote branch."""
    target = upstream_of(repo)
    tip = run_git(repo, ["rev-parse", "--verify", "-q", "HEAD^{commit}"]).stdout.strip()
    if target is None or not tip:
        return Result(["git", "push"], 1, "", "this branch tracks no branch on a remote; nothing was pushed")
    remote, destination = target
    try:
        return push_snapshot(repo, remote, tip, destination)
    except ValueError as exc:
        return Result(["git", "push"], 1, "", f"{exc}; nothing was pushed")


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
    parser = _cli.parser("push", "Push the current branch to its upstream, fast-forward only.")
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)
    result = push(args.repo)
    ok = result.returncode == 0
    return _cli.report(args, "push", ok=ok, page="Push", context=(str(args.repo),),
                       output=result.stdout + result.stderr, repository=str(args.repo),
                       message="Pushed." if ok else "git push did not finish; its own words are above.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
