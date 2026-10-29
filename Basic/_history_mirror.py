"""Plain local Git maintenance for a caller-created independent bare mirror only.

The Special operation owns selection/approval and destination creation. These helpers refuse
working trees and Git-dir redirection. They never fetch, push, reset or change host settings.
"""
from pathlib import Path

from Basic._history_read import ENV, output, refs
from Basic._run import run_checked


def _bare(repo):
    repo = Path(repo).resolve()
    if (output(repo, ["rev-parse", "--is-bare-repository"]).strip() != "true" or
            Path(output(repo, ["rev-parse", "--absolute-git-dir"]).strip()).resolve() != repo):
        raise ValueError("a direct independent bare mirror is required")
    return repo


def restore_symbols(repo, symbols, expected):
    """Recreate exact planned aliases after clone/export flattened or omitted them.

Each destination must already resolve to its exact expected rewritten commit. Aliases can
only name the explicit supplied targets, and every restored resolved id is checked again.
"""
    repo = _bare(repo)
    current, head, existing = refs(repo)
    if set(existing) - set(symbols) or any(existing[name] != symbols[name] for name in existing):
        raise ValueError("unexpected symbolic ref in mirror")
    for name, target in symbols.items():
        if not name.startswith("refs/remotes/") or target not in current or current[target] != expected[name]:
            raise ValueError("symbolic ref target does not match the plan")
    for name, target in symbols.items():
        run_checked(["git", "symbolic-ref", name, target], cwd=repo, env=ENV, timeout=30)
    after, after_head, actual = refs(repo)
    if actual != symbols or head != after_head or any(after[name] != expected[name] for name in symbols):
        raise ValueError("symbolic ref restoration failed")


def finish(repo):
    """Disconnect the clone remote without deleting tracking refs, then prune old objects.

Used after a verified all-ref rewrite with --partial, which otherwise leaves old reflogs/
objects and origin configuration. This function never runs on the source repository.
"""
    repo = _bare(repo)
    for args in (["config", "--local", "--remove-section", "remote.origin"],
                 ["reflog", "expire", "--all", "--expire=now"],
                 ["gc", "--prune=now", "--quiet"]):
        run_checked(["git", *args], cwd=repo, env=ENV, timeout=180)
