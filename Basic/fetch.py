"""Fetch a repository's remote. Moves remote-tracking refs only.

Why:          "behind" must mean behind the remote now, not at the last fetch.
Reads:        the remote.
May change:   remote-tracking refs only; never a branch or a file.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Basic: one Git or host operation.
Status:       working

    gitso fetch <repo> [--remote origin] [--dry-run]
    gitso fetch <org folder>     every repository directly inside it, one after another

With no refspec, `git fetch` updates `refs/remotes/*` and never a local branch or the working
tree -- nothing the user would have to undo. That is why observation may fetch at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic import _cli  # noqa: E402
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
    parser = _cli.parser("fetch", "Fetch a repository's remote (refs only).")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--remote", default=None, help="remote name (default: git's choice)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be fetched")
    args = parser.parse_args(argv)
    if args.repo.is_dir() and not (args.repo / ".git").exists():
        return fetch_folder(args)
    result = fetch(args.repo, args.remote, dry_run=args.dry_run)
    ok = result.returncode == 0
    return _cli.report(args, "fetch", ok=ok, page="Fetch", context=(str(args.repo),),
                       output=result.stdout + result.stderr, repository=str(args.repo),
                       message="Fetched." if ok else "git fetch did not finish; its own words are above.")


def fetch_folder(args) -> int:
    """An org-level folder: fetch every repository directly inside it (the user, 2026-11-16)."""
    repos = sorted((child for child in args.repo.iterdir() if (child / ".git").exists()),
                   key=lambda path: path.name.casefold())
    if not repos:
        return _cli.fail(args, "fetch", f"{args.repo} is not a repository and holds none directly")
    lines, failed = [], 0
    for repo in repos:
        if not _cli.machine(args):
            print(f"  fetching {repo.name}...", flush=True)
        result = fetch(repo, args.remote, dry_run=args.dry_run, quiet=True)
        if result.returncode == 0:
            lines.append(f"{repo.name}: fetched")
        else:
            failed += 1
            reason = (result.stderr or result.stdout or "git fetch failed").strip().splitlines()[-1:]
            lines.append(f"{repo.name}: FAILED ({reason[0][:160] if reason else 'no reason given'})")
    return _cli.report(args, "fetch", ok=not failed, page="Fetch", context=(str(args.repo),),
                       output="\n".join(lines) + "\n", repository=str(args.repo),
                       message=f"Fetched {len(repos) - failed} of {len(repos)} repositories."
                       + (" The failures say why above." if failed else ""))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
