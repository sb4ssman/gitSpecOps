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
from pathlib import Path

from gh_common import run_command

# Shared gh wrapper lives in shared/ at the repo root; all gh calls go through it.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.gh_cli import GhError, run_gh  # noqa: E402


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


def org_access_error(org):
    """Non-fatal read-access probe. Returns an error message, or None when accessible."""
    try:
        run_gh(['repo', 'list', org, '--limit', '1', '--json', 'name'])
        return None
    except GhError as exc:
        return str(exc)


def check_org_access(org):
    """Verify read access to an organization (write is verified at repo-create time)."""
    error = org_access_error(org)
    if error:
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
        result = run_gh([
            'api',
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


_REPO_FIELDS = 'name,createdAt,isPrivate,isFork,isArchived,description,diskUsage'


def _fetch_org_repos(org):
    """Fetch the raw repo list for an org. Raises GhError on failure."""
    result = run_gh([
        'repo', 'list', org,
        '--limit', '1000',
        '--json', _REPO_FIELDS
    ])
    return json.loads(result.stdout)


def _check_lfs_flags(org, repos):
    """Fill uses_lfs on each repo (one API probe per repo)."""
    print(f"Checking {len(repos)} repos for Git LFS usage...")
    for idx, repo in enumerate(repos, 1):
        # Clear line and print progress
        print(f"\r{' ' * 80}\r  Checking {idx}/{len(repos)}: {repo['name']}", end='', flush=True)
        repo['uses_lfs'] = check_repo_for_lfs(org, repo['name'])
    print()  # New line after progress


def get_repos_with_details(org):
    """Fetch all repos from an organization with detailed information."""
    print(f"Fetching repos from {org}...")
    try:
        repos = _fetch_org_repos(org)
    except Exception as e:
        print(f"ERROR: Failed to fetch repos from {org}")
        print(str(e))
        sys.exit(1)
    _check_lfs_flags(org, repos)
    return repos


def org_repos_with_details_safe(org):
    """Non-fatal variant for batch runs. Returns (repos with LFS flags, error)."""
    try:
        repos = _fetch_org_repos(org)
    except GhError as exc:
        return None, str(exc)
    except json.JSONDecodeError as exc:
        return None, f"gh returned invalid JSON: {exc}"
    _check_lfs_flags(org, repos)
    return repos, None


def resolve_repo_details(spec):
    """Resolve owner/name or URL into the fields used by single-repo download mode."""
    result = run_gh([
        'repo', 'view', spec.strip(), '--json',
        'name,owner,isPrivate,isFork,isArchived,diskUsage,description',
    ])
    return json.loads(result.stdout)


def create_repo(org, repo_name, private=True, description=None):
    """Create one destination repository. Confirmation policy remains with the caller."""
    args = [
        'repo', 'create', f"{org}/{repo_name}",
        '--private' if private else '--public', '--clone=false',
    ]
    if description:
        args.extend(['--description', description.replace('"', "'")])
    run_gh(args)


def ensure_repo(org, repo_name, private=True, description=None):
    """Create a repository only when it does not exist. Returns True when created."""
    existing = run_gh(['repo', 'view', f"{org}/{repo_name}"], check=False)
    if existing.returncode == 0:
        return False
    create_repo(org, repo_name, private=private, description=description)
    return True


def list_my_orgs():
    """Namespaces the authenticated account can download from: [{'login', 'role', 'state'}].

    First entry is ALWAYS the user's own account (personal: True) — personal repos are a
    download namespace just like an org. Then every org membership; role is 'admin'
    (owner) or 'member' and does not gate downloads — read access does, which the
    caller verifies per namespace.
    """
    me = run_gh(['api', 'user', '--jq', '.login']).stdout.strip()
    orgs, seen = [], set()
    if me:
        orgs.append({'login': me, 'role': 'owner', 'state': 'active', 'personal': True})
        seen.add(me)
    result = run_gh([
        'api', 'user/memberships/orgs', '--paginate',
        '--jq', '.[] | {login: .organization.login, role: .role, state: .state}'
    ])
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        login = item.get('login')
        if login and login not in seen:
            seen.add(login)
            orgs.append(item)
    return orgs


def compare_repos(source_org, dest_org, repo_name):
    """Compare two repos to see if they're identical duplicates."""
    try:
        # Get default branch info from both repos
        source_info = run_gh([
            'api', f'/repos/{source_org}/{repo_name}',
            '--jq', '{default_branch: .default_branch, size: .size}'
        ])

        dest_info = run_gh([
            'api', f'/repos/{dest_org}/{repo_name}',
            '--jq', '{default_branch: .default_branch, size: .size}'
        ])

        source_data = json.loads(source_info.stdout.strip())
        dest_data = json.loads(dest_info.stdout.strip())

        # Check if default branches match
        if source_data['default_branch'] != dest_data['default_branch']:
            return False, "Default branches don't match"

        # Get branch info from both repos
        source_branches = run_gh([
            'api', f'/repos/{source_org}/{repo_name}/branches',
            '--jq', '.[].name'
        ])

        dest_branches = run_gh([
            'api', f'/repos/{dest_org}/{repo_name}/branches',
            '--jq', '.[].name'
        ])

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
            source_sha = run_gh([
                'api', f'/repos/{source_org}/{repo_name}/branches/{branch}',
                '--jq', '.commit.sha'
            ]).stdout.strip()

            dest_sha = run_gh([
                'api', f'/repos/{dest_org}/{repo_name}/branches/{branch}',
                '--jq', '.commit.sha'
            ]).stdout.strip()

            if source_sha != dest_sha:
                return False, f"Branch '{branch}' has different HEAD commits"

        # If all branches match, repos are identical regardless of reported size
        # (GitHub's size calculation can be delayed)
        return True, "Repos are identical (all branches match)"

    except Exception as e:
        return False, f"Error comparing: {str(e)}"
