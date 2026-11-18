"""Fast-forward one repository to its upstream. Never merges, never rebases.

Why:          a fast-forward cannot lose work, so it is the one pull that needs no decision.
Reads:        the repository and its upstream.
May change:   the checked-out branch and its files, by fast-forward only.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Basic: one Git or host operation.
Status:       working

    gitso pull <repo>

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
from Basic import _cli  # noqa: E402
from Basic._facts import upstream_of  # noqa: E402
from Basic._run import run_git  # noqa: E402

EFFECT = "local"

UPDATED = "updated"
ALREADY_CURRENT = "already current"


def _head(repo: Path | str) -> str | None:
    proc = run_git(repo, ["rev-parse", "--verify", "-q", "HEAD"])
    return proc.stdout.strip() if proc.returncode == 0 else None


def fast_forward(repo: Path | str, remote: str = "origin") -> str:
    """Fetch, then `pull --ff-only`. Returns "updated", "already current", or "failed: ...".

    Whether anything moved is read from HEAD before and after, never from git's wording:
    git translates its messages, so "Already up to date." reads differently elsewhere.
    """
    # What was approved is what is pulled (an outside review, 2026-11-17): a branch that tracks
    # another remote is refused, and the pull names the remote and the branch itself.
    target = upstream_of(repo)
    if target is None:
        return "failed: this branch tracks no branch on a remote"
    if target[0] != remote:
        return f"failed: this branch tracks the remote '{target[0]}', not '{remote}'"
    fetched = run_git(repo, ["fetch", remote])
    if fetched.returncode != 0:
        return f"failed: fetch: {fetched.stderr.strip() or 'error'}"
    before = _head(repo)
    pulled = run_git(repo, ["pull", "--ff-only", "--no-rebase", "--", remote, target[1]])
    if pulled.returncode != 0:
        return f"failed: pull --ff-only: {pulled.stderr.strip() or 'not a fast-forward'}"
    return ALREADY_CURRENT if _head(repo) == before else UPDATED


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = _cli.parser("pull", "Fast-forward one repository to its upstream. Never merges, never rebases.")
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)
    result = fast_forward(args.repo)
    ok = not result.startswith("failed:")
    return _cli.report(args, "pull", ok=ok, page="Pull", context=(str(args.repo),),
                       repository=str(args.repo), result=result,
                       message=result[0].upper() + result[1:] + ("." if ok else ""))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
