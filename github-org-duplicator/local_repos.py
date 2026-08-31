"""
local_repos
===========

Local-disk side of the duplicator: discover git repositories (regular, linked worktree,
and mirror) in a folder, and delete a clone only after proving it is safe to (inside the
expected parent, actually a git repo, name as expected). Pure filesystem; no git, no network.
"""

import os
import shutil
import sys
import time
from pathlib import Path

# Shared discovery lives at the repo root. Keep direct script execution working.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.repo_discovery import find_repos  # noqa: E402


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


def safe_cleanup_directory(directory_path, expected_parent_dir, repo_name):
    """
    Safely clean up a directory, verifying it's safe to delete.

    Args:
        directory_path: Full path to directory to delete
        expected_parent_dir: Parent directory this should be in
        repo_name: Expected repository name for validation

    Returns:
        bool: True if cleanup succeeded or wasn't needed, False if unsafe
    """
    if not os.path.exists(directory_path):
        return True

    # Verify path is within expected parent (prevent path traversal)
    try:
        abs_directory = os.path.abspath(directory_path)
        abs_parent = os.path.abspath(expected_parent_dir)
        if os.path.commonpath([abs_directory, abs_parent]) != abs_parent:
            print(f"  ⚠ ERROR: Path {directory_path} is outside expected parent {expected_parent_dir}")
            return False
    except Exception as e:
        print(f"  ⚠ ERROR: Could not validate path safety: {str(e)}")
        return False

    # Verify it's actually a git repository
    is_git_repo = False
    if os.path.isdir(directory_path):
        # Check for bare repo (mirror) - has HEAD or config at root
        if os.path.exists(os.path.join(directory_path, 'HEAD')) or os.path.exists(os.path.join(directory_path, 'config')):
            is_git_repo = True
        # Check for regular repo - has .git subfolder
        elif os.path.isdir(os.path.join(directory_path, '.git')):
            is_git_repo = True

    if not is_git_repo:
        print(f"  ⚠ ERROR: {directory_path} does not appear to be a git repository")
        return False

    # Verify repo name matches expected pattern (basic check)
    dir_name = os.path.basename(directory_path)
    expected_name = repo_name if not dir_name.endswith('.git') else f"{repo_name}.git"
    if dir_name != expected_name and dir_name != repo_name:
        # Allow some flexibility for .git suffix
        if not (dir_name == f"{repo_name}.git" or dir_name == repo_name):
            print(f"  ⚠ WARNING: Directory name '{dir_name}' doesn't match expected '{repo_name}'")
            # Don't fail on this, but warn

    # Safe to delete
    try:
        shutil.rmtree(directory_path, ignore_errors=False)
        time.sleep(0.5)
        if os.path.exists(directory_path):
            print("  ⚠ Warning: Directory still exists after cleanup attempt")
            return False
        return True
    except Exception as e:
        print(f"  ⚠ Warning: Could not fully clean up directory: {str(e)}")
        return False
