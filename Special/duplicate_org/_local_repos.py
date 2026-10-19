"""
local_repos
===========

Local-disk side of the duplicator: discover git repositories (regular, linked worktree,
and mirror) in a folder, and delete a clone only after proving it is safe to (inside the
expected parent, actually a git repo, name as expected). Pure filesystem; no git, no network.
"""

import os
import shutil
import stat
import sys
from pathlib import Path

# Shared discovery lives at the repo root. Keep direct script execution working.

from Basic._discovery import classify, find_repos


def scan_local_git_repos(directory_path, recursive=False):
    """Find repositories below ``directory_path`` using shared discovery.

    ``recursive=False`` preserves the original direct-child scan scope. Recursive mode
    uses the same pruned, no-symlink, single-filesystem walk as the standalone scanner.
    """
    root = Path(directory_path)
    if not root.is_dir():
        return []

    hits = find_repos(root, max_depth=None if recursive else 0)
    repos = []
    for hit in hits:
        path = Path(hit.path)
        is_mirror = hit.kind == "bare"
        name = path.name[:-4] if is_mirror and path.name.endswith(".git") else path.name
        repos.append({
            "name": name,
            "path": str(path),
            "is_mirror": is_mirror,
            "repo_kind": hit.kind,
        })
    return repos


def duplicate_repo_names(repos):
    """Return case-insensitive destination-name collisions and their local paths."""
    grouped = {}
    for repo in repos:
        grouped.setdefault(repo["name"].lower(), []).append(repo["path"])
    return {name: paths for name, paths in grouped.items() if len(paths) > 1}


def _clear_readonly_and_retry(func, path, _exc):
    """Git marks object files read-only; on Windows `rmtree` cannot remove them until cleared."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def safe_cleanup_directory(directory_path, expected_parent_dir, repo_name):
    """Delete a clone this run made, but only after proving that is what it is.

    Refuses (returns False, deletes nothing) unless all of these hold:

    - the folder is strictly *inside* ``expected_parent_dir`` -- never the parent itself;
    - shared discovery (`Basic._discovery.classify`) calls it a repository -- the same test
      the scan uses, so "is this a repository?" can never get two answers;
    - its name is ``repo_name`` or ``repo_name.git``.

    Callers must also never pass a folder that existed before this run cloned it: a folder the
    user made is not a leftover, whatever it contains.

    Returns True if the folder is gone (or never existed), False if it was refused or survived.
    """
    if not os.path.exists(directory_path):
        return True

    try:
        abs_directory = os.path.abspath(directory_path)
        abs_parent = os.path.abspath(expected_parent_dir)
        inside = (abs_directory != abs_parent
                  and os.path.commonpath([abs_directory, abs_parent]) == abs_parent)
    except ValueError as e:  # different drives on Windows, or a mix of absolute and relative
        print(f"  ⚠ ERROR: Could not validate path safety: {e}")
        return False
    if not inside:
        print(f"  ⚠ ERROR: {directory_path} is not inside {expected_parent_dir}; not deleted")
        return False

    if classify(Path(abs_directory)) is None:
        print(f"  ⚠ ERROR: {directory_path} is not a git repository; not deleted")
        return False

    if os.path.basename(abs_directory) not in (repo_name, f"{repo_name}.git"):
        print(f"  ⚠ ERROR: {directory_path} is not named {repo_name!r}; not deleted")
        return False

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(abs_directory, onexc=_clear_readonly_and_retry)
        else:
            shutil.rmtree(abs_directory, onerror=_clear_readonly_and_retry)
    except OSError as e:
        print(f"  ⚠ Warning: Could not fully clean up directory: {e}")
        return False
    if os.path.exists(abs_directory):
        print("  ⚠ Warning: Directory still exists after cleanup attempt")
        return False
    return True
