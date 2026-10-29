"""Commit the named files of one repository, and nothing else.

    python Basic/commit.py <repo> -m MESSAGE PATH [PATH ...]

Only the paths given are committed -- added, changed or deleted -- even when other changes are
staged; those stay staged, untouched. There is no option for "everything" (`-a`), for rewriting
the last commit (`--amend`), for an empty commit, or for skipping the repository's hooks, and
there must never be one. A detached HEAD is refused: the commit would belong to no branch.

Each named path is committed as it is in the working tree (a partly staged file is committed
whole). If git refuses the commit -- a hook, a missing identity -- the named paths are left
staged and the failure is reported; nothing else in the index changes.

The identity on the commit is whatever git would use here (see `_facts.next_commit_identity`);
deciding whether that identity is the right one belongs to the caller, as does deciding *what*
to commit. This only performs it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import run_git  # noqa: E402

EFFECT = "local"

COMMITTED = "committed"
NOTHING_TO_COMMIT = "nothing to commit"


def commit(repo: Path | str, paths: list[str], message: str, *, env: dict | None = None,
           before_commit: Callable[[], None] | None = None, hooks_path: Path | None = None,
           verbatim: bool = False, timeout: float | None = None, literal_paths: bool = False) -> str:
    """Commit exactly `paths` with `message`. Returns "committed", "nothing to commit", or
    "failed: ...".

    Optional caller-owned plumbing: env pins invocation context, before_commit runs after
    adding the named paths (exceptions abort), and hooks_path selects per-command hook relay
    files without editing Git configuration. Hooks are never skipped. Verbatim message cleanup
    and a longer commit timeout are available to snapshot-aware callers. No policy lives here.
    """
    if not paths:
        return "failed: no paths named (this never commits everything)"
    if not message.strip():
        return "failed: empty commit message"
    if run_git(repo, ["symbolic-ref", "-q", "HEAD"], env=env).returncode != 0:
        return "failed: detached HEAD: the commit would belong to no branch"
    # Per-path magic keeps hook subprocesses' own pathspec environment unchanged.
    pathspecs = [f":(top,literal){path}" for path in paths] if literal_paths else paths
    changed = run_git(repo, ["status", "--porcelain", "--untracked-files=all", "--", *pathspecs], env=env)
    if changed.returncode != 0:
        return f"failed: status: {changed.stderr.strip() or 'error'}"
    if not changed.stdout.strip():
        return NOTHING_TO_COMMIT
    # `add` makes a new file known (and records a deletion); `--only` then commits these paths
    # alone, whatever else the index holds.
    added = run_git(repo, ["add", "--", *pathspecs], env=env)
    if added.returncode != 0:
        return f"failed: add: {added.stderr.strip() or 'error'}"
    if before_commit is not None:
        before_commit()
    arguments = []
    if hooks_path is not None:
        arguments += ["-c", f"core.hooksPath={hooks_path}"]
    arguments += ["commit", "--quiet", "--only"]
    if verbatim:
        arguments.append("--cleanup=verbatim")
    arguments += ["-m", message, "--", *pathspecs]
    made = run_git(repo, arguments, env=env, timeout=timeout)
    if made.returncode != 0:
        detail = (made.stderr.strip() or made.stdout.strip() or "refused").splitlines()
        return f"failed: commit: {detail[-1] if detail else 'refused'}"
    return COMMITTED


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Commit the named files, and nothing else.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("-m", "--message", required=True)
    parser.add_argument("paths", nargs="+", metavar="PATH")
    args = parser.parse_args(argv)
    result = commit(args.repo, args.paths, args.message)
    print(result)
    return 1 if result.startswith("failed:") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
