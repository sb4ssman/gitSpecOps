"""Fetch a repository's remote. Moves remote-tracking refs only.

    python Basic/fetch.py <repo> [--remote origin] [--dry-run]

With no refspec, `git fetch` updates `refs/remotes/*` and never a local branch or the working
tree -- nothing the user would have to undo. That is why observation may fetch at all.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import Result, run_git  # noqa: E402

EFFECT = "none"


def fetch(repo: Path | str, remote: str | None = None, *, dry_run: bool = False,
          quiet: bool = False, timeout: float | None = None) -> Result:
    """`git fetch [--dry-run] [--quiet] [remote]` with no refspec. Never raises."""
    args = ["fetch"]
    if dry_run:
        args.append("--dry-run")
    if quiet:
        args.append("--quiet")
    if remote:
        args.append(remote)
    return run_git(repo, args, timeout=timeout)


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Fetch a repository's remote (refs only).")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--remote", default=None, help="remote name (default: git's choice)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be fetched")
    args = parser.parse_args(argv)
    result = fetch(args.repo, args.remote, dry_run=args.dry_run)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
