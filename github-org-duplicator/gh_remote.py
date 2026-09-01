"""
gh_remote
=========

Everything that talks to GitHub through the `gh` CLI: environment/prerequisite checks,
fetching an org's repo inventory (with Git LFS detection), and comparing two repos to
decide whether they're already identical duplicates. No other module shells out to `gh`.
"""

import base64
import binascii
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gh_common import run_command

# The .gitattributes probe is a tiny single-file API read; it must never sit on the default
# 120s gh timeout, and several can run at once.
_LFS_PROBE_TIMEOUT = 20
_LFS_PROBE_WORKERS = 8

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
    """Best-effort: does this repo's .gitattributes declare an LFS filter?

    A network/timeout error or a repo without .gitattributes both mean "assume not" — this
    only drives a warning line, never behaviour, so it must never raise.
    """
    try:
        result = run_gh([
            'api', f'/repos/{org}/{repo_name}/contents/.gitattributes', '--jq', '.content'
        ], check=False, timeout=_LFS_PROBE_TIMEOUT)
    except GhError:
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        content = base64.b64decode(result.stdout.strip()).decode('utf-8', errors='ignore')
    except (binascii.Error, ValueError):
        return False
    return 'filter=lfs' in content


_REPO_FIELDS = 'name,createdAt,isPrivate,isFork,isArchived,description,diskUsage'


def _fetch_org_repos(org):
    """Fetch the raw repo list for an org. Raises GhError on an empty/failed response."""
    result = run_gh(['repo', 'list', org, '--limit', '1000', '--json', _REPO_FIELDS])
    text = (result.stdout or "").strip()
    if not text:
        raise GhError(f"gh returned an empty repo list for {org}")
    return json.loads(text)


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
        repo['uses_lfs'] = check_repo_for_lfs(org, repo['name'])
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
    """Resolve owner/name or URL into the fields used by single-repo download mode.

    Raises GhError (missing repo / no access / bad spec) or json.JSONDecodeError.
    """
    spec = spec.strip()
    if not spec or spec.startswith("-"):
        raise GhError(f"not a repository spec: {spec!r}")
    result = run_gh([
        'repo', 'view', spec, '--json',
        'name,owner,isPrivate,isFork,isArchived,diskUsage,description',
    ])
    text = (result.stdout or "").strip()
    if not text:
        raise GhError(f"gh returned nothing for {spec!r}")
    return json.loads(text)


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
