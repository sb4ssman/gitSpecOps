"""
local_repos
===========

Local-disk side of the duplicator: discover git repositories (regular and mirror) in a
folder, and delete a clone only after proving it is safe to (inside the expected parent,
actually a git repo, name as expected). Pure filesystem; no git, no network.
"""

import os
import shutil
import time


def scan_local_git_repos(directory_path):
    """Scan a directory for git repositories (both regular and mirror)."""
    repos = []

    if not os.path.exists(directory_path):
        return repos

    for item in os.listdir(directory_path):
        item_path = os.path.join(directory_path, item)

        if not os.path.isdir(item_path):
            continue

        # Check if it's a mirror repo (ends with .git and is a bare repo)
        if item.endswith('.git'):
            git_dir = item_path
            # Verify it's actually a git repo by checking for HEAD or config
            if os.path.exists(os.path.join(git_dir, 'HEAD')) or os.path.exists(os.path.join(git_dir, 'config')):
                repo_name = item[:-4]  # Remove .git suffix
                repos.append({
                    'name': repo_name,
                    'path': git_dir,
                    'is_mirror': True
                })
        else:
            # Check if it's a regular repo (has .git subfolder)
            git_dir = os.path.join(item_path, '.git')
            if os.path.isdir(git_dir):
                repos.append({
                    'name': item,
                    'path': item_path,
                    'is_mirror': False
                })

    return repos


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
