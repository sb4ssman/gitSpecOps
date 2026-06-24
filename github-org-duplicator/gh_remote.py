"""
gh_remote
=========

Everything that talks to GitHub through the `gh` CLI: environment/prerequisite checks,
fetching an org's repo inventory (with Git LFS detection), and comparing two repos to
decide whether they're already identical duplicates. No other module shells out to `gh`.
"""

import base64
import json
import sys

from gh_common import run_command


# -------------------------------------------------------------------------------------
# Environment / prerequisite checks
# -------------------------------------------------------------------------------------
def check_git_installed():
    """Verify git is installed."""
    try:
        run_command(['git', '--version'], check=True)
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
        run_command(['gh', '--version'], check=True)
        print("✓ gh CLI installed")
        return True
    except Exception:
        print("✗ GitHub CLI (gh) is not installed")
        print("Install GitHub CLI and rerun this tool:")
        print("  Windows: winget install --id GitHub.cli")
        print("  macOS: brew install gh")
        print("  Linux: See https://cli.github.com/")
        sys.exit(1)


def check_gh_authenticated():
    """Verify gh is authenticated."""
    try:
        run_command(['gh', 'auth', 'status'], check=True)
        print("✓ gh authenticated")
    except Exception:
        print("ERROR: gh is not authenticated.")
        print("Run: gh auth login")
        sys.exit(1)


def setup_git_credentials():
    """Ensure git uses gh credentials."""
    try:
        run_command(['gh', 'auth', 'setup-git'], check=True)
        print("✓ git configured to use gh credentials")
    except Exception:
        print("WARNING: Could not configure git to use gh credentials")
        print("You may need to run: gh auth setup-git")


def check_org_access(org):
    """Verify read access to an organization (write is verified at repo-create time)."""
    try:
        run_command(['gh', 'repo', 'list', org, '--limit', '1', '--json', 'name'], check=True)
        return True
    except Exception:
        print(f"ERROR: Cannot access organization '{org}'")
        print("Make sure you have access and the org name is correct.")
        sys.exit(1)


# -------------------------------------------------------------------------------------
# Inventory + duplicate detection
# -------------------------------------------------------------------------------------
def check_repo_for_lfs(org, repo_name):
    """Check if a repository uses Git LFS by looking for .gitattributes with LFS filters."""
    try:
        # Fetch .gitattributes file content
        result = run_command([
            'gh', 'api',
            f'/repos/{org}/{repo_name}/contents/.gitattributes',
            '--jq', '.content'
        ], check=False)

        if result.returncode == 0:
            # Decode base64 content
            content = base64.b64decode(result.stdout.strip()).decode('utf-8', errors='ignore')
            if 'filter=lfs' in content:
                return True
    except Exception:
        pass
    return False


def get_repos_with_details(org):
    """Fetch all repos from an organization with detailed information."""
    print(f"Fetching repos from {org}...")
    try:
        result = run_command([
            'gh', 'repo', 'list', org,
            '--limit', '1000',
            '--json', 'name,createdAt,isPrivate,description,diskUsage'
        ])
    except Exception as e:
        print(f"ERROR: Failed to fetch repos from {org}")
        print(str(e))
        sys.exit(1)

    repos = json.loads(result.stdout)

    # Check each repo for LFS
    print(f"Checking {len(repos)} repos for Git LFS usage...")
    for idx, repo in enumerate(repos, 1):
        # Clear line and print progress
        print(f"\r{' ' * 80}\r  Checking {idx}/{len(repos)}: {repo['name']}", end='', flush=True)
        repo['uses_lfs'] = check_repo_for_lfs(org, repo['name'])
    print()  # New line after progress

    return repos


def compare_repos(source_org, dest_org, repo_name):
    """Compare two repos to see if they're identical duplicates."""
    try:
        # Get default branch info from both repos
        source_info = run_command([
            'gh', 'api', f'/repos/{source_org}/{repo_name}',
            '--jq', '{default_branch: .default_branch, size: .size}'
        ], check=True)

        dest_info = run_command([
            'gh', 'api', f'/repos/{dest_org}/{repo_name}',
            '--jq', '{default_branch: .default_branch, size: .size}'
        ], check=True)

        source_data = json.loads(source_info.stdout.strip())
        dest_data = json.loads(dest_info.stdout.strip())

        # Check if default branches match
        if source_data['default_branch'] != dest_data['default_branch']:
            return False, "Default branches don't match"

        # Get branch info from both repos
        source_branches = run_command([
            'gh', 'api', f'/repos/{source_org}/{repo_name}/branches',
            '--jq', '.[].name'
        ], check=True)

        dest_branches = run_command([
            'gh', 'api', f'/repos/{dest_org}/{repo_name}/branches',
            '--jq', '.[].name'
        ], check=True)

        source_branch_list = set(source_branches.stdout.strip().split('\n')) if source_branches.stdout.strip() else set()
        dest_branch_list = set(dest_branches.stdout.strip().split('\n')) if dest_branches.stdout.strip() else set()

        # If dest has no branches at all, it's empty
        if not dest_branch_list and source_branch_list:
            return False, "Destination repo has no branches"

        # Compare branch names
        if source_branch_list != dest_branch_list:
            return False, f"Branch count mismatch (source: {len(source_branch_list)}, dest: {len(dest_branch_list)})"

        # For each branch, compare the HEAD commit SHA
        for branch in source_branch_list:
            source_sha = run_command([
                'gh', 'api', f'/repos/{source_org}/{repo_name}/branches/{branch}',
                '--jq', '.commit.sha'
            ], check=True).stdout.strip()

            dest_sha = run_command([
                'gh', 'api', f'/repos/{dest_org}/{repo_name}/branches/{branch}',
                '--jq', '.commit.sha'
            ], check=True).stdout.strip()

            if source_sha != dest_sha:
                return False, f"Branch '{branch}' has different HEAD commits"

        # If all branches match, repos are identical regardless of reported size
        # (GitHub's size calculation can be delayed)
        return True, "Repos are identical (all branches match)"

    except Exception as e:
        return False, f"Error comparing: {str(e)}"
