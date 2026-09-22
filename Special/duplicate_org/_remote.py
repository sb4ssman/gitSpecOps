"""
gh_remote
=========

The org duplicator's side of talking to GitHub: prerequisite checks that print and stop, and
the pooled LFS probe with progress. The `gh` calls themselves live in
`Basic/_providers/github.py`; this module only decides how the duplicator reports them.
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor


from Basic._providers.github import (
    GhError,
    check_repo_for_lfs,
    fetch_org_repos,
    org_access_error,
    run_gh,
)
from Basic._run import run_checked

# The .gitattributes probe is a tiny single-file API read; it must never sit on the default
# 120s gh timeout, and several can run at once.
_LFS_PROBE_TIMEOUT = 20
_LFS_PROBE_WORKERS = 8


# -------------------------------------------------------------------------------------
# Environment / prerequisite checks
# -------------------------------------------------------------------------------------
def check_git_installed():
    """Verify git is installed."""
    try:
        run_checked(['git', '--version'], timeout=30)
        print("✓ git installed")
        return True
    except Exception:
        print("✗ git is not installed")
        print("Install git and rerun this tool:")
        print("  Windows: https://git-scm.com/download/win")
        print("  macOS: https://git-scm.com/download/mac")
        print("  Linux: Use your distribution's package manager")
        sys.exit(1)


def check_gh_installed():
    """Verify gh CLI is installed."""
    try:
        run_gh(['--version'])
        print("✓ gh CLI installed")
        return True
    except GhError:
        print("✗ GitHub CLI (gh) is not installed")
        print("Install GitHub CLI and rerun this tool:")
        print("  Windows: winget install --id GitHub.cli")
        print("  macOS: brew install gh")
        print("  Linux: See https://cli.github.com/")
        sys.exit(1)


def check_gh_authenticated():
    """Verify gh is authenticated."""
    try:
        run_gh(['auth', 'status'])
        print("✓ gh authenticated")
    except GhError:
        print("ERROR: gh is not authenticated.")
        print("Run: gh auth login")
        sys.exit(1)


def remind_git_credentials():
    """Keep credential configuration user-owned while explaining private-clone setup."""
    print("ℹ Git credentials are user-managed. If private clones fail, run: gh auth setup-git")


def check_org_access(org):
    """Verify read access to an organization (write is verified at repo-create time)."""
    error = org_access_error(org)
    if error:
        print(f"ERROR: Cannot access organization '{org}'")
        print("Make sure you have access and the org name is correct.")
        sys.exit(1)


# -------------------------------------------------------------------------------------
# Inventory with LFS flags
# -------------------------------------------------------------------------------------
def _check_lfs_flags(org, repos):
    """Fill uses_lfs on each repo. One tiny API probe per repo, run in a small pool so a
    150-repo namespace is ~20s instead of minutes (and a slow probe can't stall the rest)."""
    if not repos:
        return
    total = len(repos)
    tty = sys.stdout.isatty()
    print(f"Checking {total} repos for Git LFS usage...")
    progress = {'done': 0}
    lock = threading.Lock()

    def probe(repo):
        repo['uses_lfs'] = check_repo_for_lfs(org, repo['name'], timeout=_LFS_PROBE_TIMEOUT)
        with lock:
            progress['done'] += 1
            if tty:
                print(f"\r  checked {progress['done']}/{total}", end='', flush=True)

    with ThreadPoolExecutor(max_workers=_LFS_PROBE_WORKERS) as pool:
        list(pool.map(probe, repos))
    print(f"\r  checked {total}/{total}")


def get_repos_with_details(org):
    """Fetch all repos from an organization with detailed information."""
    print(f"Fetching repos from {org}...")
    try:
        repos = fetch_org_repos(org)
    except Exception as e:
        print(f"ERROR: Failed to fetch repos from {org}")
        print(str(e))
        sys.exit(1)
    _check_lfs_flags(org, repos)
    return repos


def org_repos_with_details_safe(org):
    """Non-fatal variant for batch runs. Returns (repos with LFS flags, error)."""
    try:
        repos = fetch_org_repos(org)
    except GhError as exc:
        return None, str(exc)
    except ValueError as exc:  # json.JSONDecodeError
        return None, f"gh returned invalid JSON: {exc}"
    _check_lfs_flags(org, repos)
    return repos, None
