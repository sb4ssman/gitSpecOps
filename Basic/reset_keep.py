"""Move one repository's checked-out branch to another commit, keeping uncommitted edits.

    python Basic/reset_keep.py <repo> <target>

`git reset --keep` moves the branch and updates the files that differ between the two commits,
and refuses outright if any of those files has an uncommitted change -- so an edit is never
overwritten. There is no option for `--hard`, `--mixed` or `--soft`, and there must never be one:
the mirror of `pull --ff-only` and of a push that cannot force.

What it does **not** protect is commits. A commit on the branch that `target` does not contain is
left on no branch (still in the reflog, until git expires it). Deciding whether that is
acceptable -- proving nothing unpushed would be hidden, then asking the person -- belongs to the
caller. This only performs the move.
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

MOVED = "moved"
ALREADY_THERE = "already there"


def _commit(repo: Path | str, revision: str) -> str | None:
    proc = run_git(repo, ["rev-parse", "--verify", "-q", f"{revision}^{{commit}}"])
    return proc.stdout.strip() if proc.returncode == 0 else None


def reset_keep(repo: Path | str, target: str) -> str:
    """`git reset --keep <target>` on the checked-out branch.

    Returns "moved", "already there", or "failed: ...". A detached HEAD is refused: there is no
    branch to move. The target is resolved to a commit id first, so a ref that shares its name
    with a file can never be read as a path.
    """
    if run_git(repo, ["symbolic-ref", "-q", "HEAD"]).returncode != 0:
        return "failed: detached HEAD: check out the branch to move first"
    wanted = _commit(repo, target)
    if wanted is None:
        return f"failed: {target} is not a commit in this repository"
    if _commit(repo, "HEAD") == wanted:
        return ALREADY_THERE
    moved = run_git(repo, ["reset", "--keep", wanted])
    if moved.returncode != 0:
        return f"failed: reset --keep: {moved.stderr.strip() or 'refused'}"
    return MOVED


def main(argv: list[str]) -> int:
    enable_unicode_output()
    if len(argv) != 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    result = reset_keep(Path(argv[0]), argv[1])
    print(result)
    return 1 if result.startswith("failed:") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
