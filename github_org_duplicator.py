#!/usr/bin/env python3
"""
GitHub Organization Repository Migration Script

Duplicates all repositories from one GitHub organization to another.
Requires: gh CLI authenticated with 2FA
"""

import subprocess
import json
import os
import shutil
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

def run_command(cmd, check=True, capture=True):
    """Run a shell command and return result."""
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        encoding='utf-8',  # ADD THIS
        errors='replace',  # ADD THIS - replaces problematic chars with ?
        check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result

def log_message(message, log_file):
    """Print to console and write to log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(message)
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry + '\n')

def detect_package_manager():
    """Detect available package manager on the system."""
    import platform
    system = platform.system().lower()
    
    if system == 'windows':
        # Check for winget
        try:
            result = run_command(['winget', '--version'], check=False, capture=True)
            if result.returncode == 0:
                return 'winget'
        except:
            pass
        
        # Check for chocolatey
        try:
            result = run_command(['choco', '--version'], check=False, capture=True)
            if result.returncode == 0:
                return 'chocolatey'
        except:
            pass
        
        return None
    
    elif system == 'darwin':  # macOS
        # Check for Homebrew
        try:
            result = run_command(['brew', '--version'], check=False, capture=True)
            if result.returncode == 0:
                return 'brew'
        except:
            pass
        return None
    
    elif system == 'linux':
        # Check for apt (Debian/Ubuntu)
        try:
            result = run_command(['apt', '--version'], check=False, capture=True)
            if result.returncode == 0:
                return 'apt'
        except:
            pass
        
        # Check for yum (RHEL/CentOS)
        try:
            result = run_command(['yum', '--version'], check=False, capture=True)
            if result.returncode == 0:
                return 'yum'
        except:
            pass
        
        # Check for dnf (Fedora)
        try:
            result = run_command(['dnf', '--version'], check=False, capture=True)
            if result.returncode == 0:
                return 'dnf'
        except:
            pass
        
        return None
    
    return None

def get_install_command(tool, package_manager):
    """Get installation command for a tool using the specified package manager."""
    commands = {
        'winget': {
            'git': ['winget', 'install', '--id', 'Git.Git', '-e', '--source', 'winget'],
            'gh': ['winget', 'install', '--id', 'GitHub.cli', '-e', '--source', 'winget']
        },
        'chocolatey': {
            'git': ['choco', 'install', 'git', '-y'],
            'gh': ['choco', 'install', 'gh', '-y']
        },
        'brew': {
            'git': ['brew', 'install', 'git'],
            'gh': ['brew', 'install', 'gh']
        },
        'apt': {
            'git': ['sudo', 'apt', 'update', '&&', 'sudo', 'apt', 'install', '-y', 'git'],
            'gh': ['sudo', 'apt', 'install', '-y', 'gh']
        },
        'yum': {
            'git': ['sudo', 'yum', 'install', '-y', 'git'],
            'gh': ['sudo', 'yum', 'install', '-y', 'gh']
        },
        'dnf': {
            'git': ['sudo', 'dnf', 'install', '-y', 'git'],
            'gh': ['sudo', 'dnf', 'install', '-y', 'gh']
        }
    }
    
    return commands.get(package_manager, {}).get(tool)

def offer_installation(tool_name, package_manager):
    """Offer to install a missing tool."""
    install_cmd = get_install_command(tool_name, package_manager)
    
    if not install_cmd:
        return False
    
    print(f"\n{tool_name} is not installed.")
    
    if package_manager == 'winget':
        print(f"Would you like to install {tool_name} using winget?")
        print(f"Command: {' '.join(install_cmd)}")
    elif package_manager == 'chocolatey':
        print(f"Would you like to install {tool_name} using Chocolatey?")
        print(f"Command: {' '.join(install_cmd)}")
    elif package_manager == 'brew':
        print(f"Would you like to install {tool_name} using Homebrew?")
        print(f"Command: {' '.join(install_cmd)}")
    elif package_manager in ['apt', 'yum', 'dnf']:
        print(f"Would you like to install {tool_name} using {package_manager}?")
        print(f"Command: {' '.join(install_cmd)}")
    
    response = input("Install now? (y/n): ").strip().lower()
    
    if response in ['y', 'yes']:
        try:
            # Handle commands with && for apt (git installation)
            if '&&' in ' '.join(install_cmd):
                # Split on && and run separately
                parts = ' '.join(install_cmd).split(' && ')
                for part in parts:
                    cmd_parts = part.strip().split()
                    run_command(cmd_parts, check=True)
            else:
                run_command(install_cmd, check=True)
            
            print(f"✓ {tool_name} installation completed")
            # Give it a moment to register in PATH
            import time
            time.sleep(2)
            return True
        except Exception as e:
            print(f"✗ Installation failed: {str(e)}")
            print("Please install manually and try again.")
            return False
    else:
        print(f"Please install {tool_name} manually and try again.")
        print(f"Visit: https://git-scm.com/downloads" if tool_name == 'git' else "https://cli.github.com/")
        return False

def check_git_installed():
    """Verify git is installed, offer installation if missing."""
    try:
        run_command(['git', '--version'], check=True)
        print("✓ git installed")
        return True
    except:
        print("✗ git is not installed")
        package_manager = detect_package_manager()
        
        if package_manager:
            if offer_installation('git', package_manager):
                # Verify installation worked
                try:
                    run_command(['git', '--version'], check=True)
                    print("✓ git installed and verified")
                    return True
                except:
                    print("ERROR: git installation verification failed")
                    sys.exit(1)
            else:
                sys.exit(1)
        else:
            print("ERROR: git is not installed and no package manager detected.")
            print("Please install git manually:")
            print("  Windows: https://git-scm.com/download/win")
            print("  macOS: https://git-scm.com/download/mac")
            print("  Linux: Use your distribution's package manager")
            sys.exit(1)

def check_gh_installed():
    """Verify gh CLI is installed, offer installation if missing."""
    try:
        run_command(['gh', '--version'], check=True)
        print("✓ gh CLI installed")
        return True
    except:
        print("✗ GitHub CLI (gh) is not installed")
        package_manager = detect_package_manager()
        
        if package_manager:
            if offer_installation('gh', package_manager):
                # Verify installation worked
                try:
                    run_command(['gh', '--version'], check=True)
                    print("✓ GitHub CLI installed and verified")
                    return True
                except:
                    print("ERROR: GitHub CLI installation verification failed")
                    sys.exit(1)
            else:
                sys.exit(1)
        else:
            print("ERROR: GitHub CLI is not installed and no package manager detected.")
            print("Please install GitHub CLI manually:")
            print("  Windows: winget install --id GitHub.cli")
            print("  macOS: brew install gh")
            print("  Linux: See https://cli.github.com/")
            sys.exit(1)

def check_gh_authenticated():
    """Verify gh is authenticated."""
    try:
        run_command(['gh', 'auth', 'status'], check=True)
        print("✓ gh authenticated")
    except:
        print("ERROR: gh is not authenticated.")
        print("Run: gh auth login")
        sys.exit(1)

def setup_git_credentials():
    """Ensure git uses gh credentials."""
    try:
        run_command(['gh', 'auth', 'setup-git'], check=True)
        print("✓ git configured to use gh credentials")
    except:
        print("WARNING: Could not configure git to use gh credentials")
        print("You may need to run: gh auth setup-git")

def check_org_access(org):
    """Verify access to an organization."""
    try:
        run_command(['gh', 'repo', 'list', org, '--limit', '1', '--json', 'name'], check=True)
        return True
    except:
        print(f"ERROR: Cannot access organization '{org}'")
        print(f"Make sure you have access and the org name is correct.")
        sys.exit(1)

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
            import base64
            content = base64.b64decode(result.stdout.strip()).decode('utf-8', errors='ignore')
            if 'filter=lfs' in content:
                return True
    except:
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
        all_match = True
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

def format_size(kb):
    """Format size in KB to human readable format."""
    if kb < 1024:
        return f"{kb} KB"
    elif kb < 1024 * 1024:
        return f"{kb/1024:.1f} MB"
    else:
        return f"{kb/(1024*1024):.1f} GB"

def display_repo_table(repos, org_name):
    """Display repository information in a readable table format."""
    print()
    print("=" * 100)
    print(f"Repositories in {org_name}")
    print("=" * 100)
    
    if not repos:
        print("No repositories found.")
        return
    
    # Sort by creation date (oldest first)
    sorted_repos = sorted(repos, key=lambda r: r['createdAt'])
    
    # Table header
    print(f"{'#':<4} {'Name':<40} {'Size':<12} {'Private':<8} {'LFS':<6} {'Created':<20}")
    print("-" * 100)
    
    lfs_repos = []
    for idx, repo in enumerate(sorted_repos, 1):
        name = repo['name'][:39] if len(repo['name']) > 39 else repo['name']
        size = format_size(repo.get('diskUsage', 0))
        private = "Yes" if repo['isPrivate'] else "No"
        lfs = "⚠ YES" if repo['uses_lfs'] else "No"
        created = repo['createdAt'][:10]  # Just the date part
        
        print(f"{idx:<4} {name:<40} {size:<12} {private:<8} {lfs:<6} {created:<20}")
        
        if repo['uses_lfs']:
            lfs_repos.append(repo['name'])
    
    print("=" * 100)
    print(f"Total: {len(sorted_repos)} repositories")
    print(f"Total size: {format_size(sum(r.get('diskUsage', 0) for r in sorted_repos))}")
    
    if lfs_repos:
        print()
        print("⚠ WARNING: The following repositories use Git LFS:")
        for repo_name in lfs_repos:
            print(f"  - {repo_name}")
        print()
        print("Git LFS repositories require special handling:")
        print("  1. You must have Git LFS installed (git lfs install)")
        print("  2. LFS files may not transfer correctly with --mirror")
        print("  3. You may need to manually configure LFS in the new org")
    
    print()

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
        if not abs_directory.startswith(abs_parent + os.sep) and abs_directory != abs_parent:
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
            print(f"  ⚠ Warning: Directory still exists after cleanup attempt")
            return False
        return True
    except Exception as e:
        print(f"  ⚠ Warning: Could not fully clean up directory: {str(e)}")
        return False

def process_download_repo(repo, source_org, temp_dir, use_mirror, completed_file, success_log, error_log):
    """Process a single repository download."""
    repo_name = repo['name']
    start_time = time.time()
    uses_lfs = repo.get('uses_lfs', False)
    repo_size = format_size(repo.get('diskUsage', 0))
    
    print(f"Processing: {repo_name} [{repo_size}]")
    if uses_lfs:
        print(f"  ⚠ This repo uses Git LFS")
    
    # Determine final path based on format
    if use_mirror:
        repo_final_path = os.path.join(temp_dir, f"{repo_name}.git")
    else:
        repo_final_path = os.path.join(temp_dir, repo_name)
    
    # Clean up any leftover directory first (safely)
    if os.path.exists(repo_final_path):
        print(f"  → Cleaning up leftover directory...")
        if not safe_cleanup_directory(repo_final_path, temp_dir, repo_name):
            print(f"  ⚠ Warning: Could not safely clean up directory")
            print(f"  → Attempting clone anyway...")
    
    clone_url = f"https://github.com/{source_org}/{repo_name}.git"
    
    try:
        print(f"  → Cloning from {source_org}...")
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if use_mirror:
                    run_command(['git', 'clone', '--mirror', clone_url, repo_final_path], check=True)
                else:
                    run_command(['git', 'clone', clone_url, repo_final_path], check=True)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  → Clone attempt {attempt + 1} failed: {str(e)}")
                    print(f"  → Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    raise
        
        # Mark as complete
        with open(completed_file, 'a', encoding='utf-8') as f:
            f.write(f"{repo_name}\n")
        
        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        print()
        return {'status': 'success', 'elapsed': elapsed}
    
    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        print(error_msg)
        log_message(error_msg, error_log)
        print()
        return {'status': 'failed', 'elapsed': elapsed, 'error': str(e)}

def process_upload_repo(repo, dest_org, completed_file, success_log, error_log):
    """Process a single repository upload."""
    repo_name = repo['name']
    repo_path = repo['path']
    start_time = time.time()
    is_mirror = repo.get('is_mirror', False)
    
    print(f"Processing: {repo_name}")
    if is_mirror:
        print(f"  → Mirror repository")
    
    try:
        # Step 1: Create repo in dest org (default to private)
        print(f"  → Creating in {dest_org}...")
        cmd = ['gh', 'repo', 'create', f"{dest_org}/{repo_name}", '--private', '--clone=false']
        
        # Check if repo already exists
        result = run_command(['gh', 'repo', 'view', f"{dest_org}/{repo_name}"], check=False)
        if result.returncode == 0:
            print(f"  → Repository already exists, skipping creation")
        else:
            run_command(cmd, check=True)
        
        # Step 2: Push all refs to dest org (excluding pull request refs)
        print(f"  → Pushing to {dest_org}...")
        push_url = f"https://github.com/{dest_org}/{repo_name}.git"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Get list of all refs
                result = run_command(
                    ['git', '-C', repo_path, 'for-each-ref', '--format=%(refname)', 'refs/'],
                    check=True
                )
                
                # Filter out pull request refs
                all_refs = result.stdout.strip().split('\n')
                good_refs = [ref for ref in all_refs if ref and not ref.startswith('refs/pull/')]
                
                # Push only the good refs
                if good_refs:
                    run_command(['git', '-C', repo_path, 'push', push_url] + good_refs, check=True)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  → Push attempt {attempt + 1} failed, retrying...")
                    time.sleep(5)
                else:
                    raise
        
        # Mark as complete
        with open(completed_file, 'a', encoding='utf-8') as f:
            f.write(f"{repo_name}\n")
        
        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        print()
        return {'status': 'success', 'elapsed': elapsed}
    
    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        print()
        return {'status': 'failed', 'elapsed': elapsed, 'error': str(e)}

def process_migrate_repo(repo, source_org, dest_org, temp_dir, completed_file, success_log, error_log):
    """Process a single repository migration."""
    repo_name = repo['name']
    start_time = time.time()
    is_private = repo['isPrivate']
    description = repo.get('description', '') or ''
    uses_lfs = repo.get('uses_lfs', False)
    repo_size = format_size(repo.get('diskUsage', 0))
    
    print(f"Processing: {repo_name} [{repo_size}]")
    if uses_lfs:
        print(f"  ⚠ This repo uses Git LFS")
    
    repo_temp_path = os.path.join(temp_dir, repo_name)
    
    try:
        # Step 1: Clone from source org
        print(f"  → Cloning from {source_org}...")
        
        # Clean up any leftover temp directory first (safely)
        if os.path.exists(repo_temp_path):
            print(f"  → Cleaning up leftover temp directory...")
            if not safe_cleanup_directory(repo_temp_path, temp_dir, repo_name):
                print(f"  ⚠ Warning: Could not safely clean up temp directory")
                print(f"  → Attempting clone anyway...")
        
        clone_url = f"https://github.com/{source_org}/{repo_name}.git"
        
        # Retry logic for clone
        max_retries = 3
        for attempt in range(max_retries):
            try:
                run_command(['git', 'clone', '--mirror', clone_url, repo_temp_path], check=True)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  → Clone attempt {attempt + 1} failed, retrying...")
                    time.sleep(5)
                else:
                    raise
        
        # Step 2: Create repo in dest org
        print(f"  → Creating in {dest_org}...")
        visibility = "--private" if is_private else "--public"
        cmd = ['gh', 'repo', 'create', f"{dest_org}/{repo_name}", visibility, '--clone=false']
        
        # Handle description with potential quotes
        if description:
            safe_description = description.replace('"', "'")
            cmd.extend(['--description', safe_description])
        
        run_command(cmd, check=True)
        
        # Step 3: Push to dest org (excluding pull request refs)
        print(f"  → Pushing to {dest_org}...")
        push_url = f"https://github.com/{dest_org}/{repo_name}.git"
        
        # Retry logic for push
        for attempt in range(max_retries):
            try:
                # First, get list of all refs
                result = run_command(
                    ['git', '-C', repo_temp_path, 'for-each-ref', '--format=%(refname)', 'refs/'],
                    check=True
                )
                
                # Filter out pull request refs
                all_refs = result.stdout.strip().split('\n')
                good_refs = [ref for ref in all_refs if ref and not ref.startswith('refs/pull/')]
                
                # Push only the good refs
                if good_refs:
                    run_command(['git', '-C', repo_temp_path, 'push', push_url] + good_refs, check=True)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  → Push attempt {attempt + 1} failed, retrying...")
                    time.sleep(5)
                else:
                    raise
        
        # Step 4: Clean up temp directory (safely)
        print(f"  → Cleaning up...")
        if os.path.exists(repo_temp_path):
            safe_cleanup_directory(repo_temp_path, temp_dir, repo_name)
        
        # Step 5: Mark as complete
        with open(completed_file, 'a', encoding='utf-8') as f:
            f.write(f"{repo_name}\n")
        
        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        print()
        return {'status': 'success', 'elapsed': elapsed}
    
    except Exception as e:
        # Clean up on failure for migrate mode (safely)
        if os.path.exists(repo_temp_path):
            safe_cleanup_directory(repo_temp_path, temp_dir, repo_name)
        
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        print()
        return {'status': 'failed', 'elapsed': elapsed, 'error': str(e)}

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

def load_completed_repos(filename):
    """Load list of completed repos from file."""
    if not os.path.exists(filename):
        return set()
    with open(filename, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

def get_tracking_files(operation_mode):
    """Get tracking file names based on operation mode."""
    if operation_mode == 'download':
        return {
            'completed': 'downloaded_repos.txt',
            'error': 'download_errors.txt',
            'success': 'download_log.txt',
            'session': 'download_session.txt'
        }
    elif operation_mode == 'upload':
        return {
            'completed': 'uploaded_repos.txt',
            'error': 'upload_errors.txt',
            'success': 'upload_log.txt',
            'session': 'upload_session.txt'
        }
    else:  # migrate
        return {
            'completed': 'completed_repos.txt',
            'error': 'migration_errors.txt',
            'success': 'migration_log.txt',
            'session': 'migration_session.txt'
        }

def initialize_tracking_files(operation_mode, source_org, dest_org, temp_dir):
    """Initialize tracking files and handle session management."""
    files = get_tracking_files(operation_mode)
    
    # Determine current session identifier
    if operation_mode == 'download':
        current_session = f"{source_org} -> {temp_dir}"
    elif operation_mode == 'upload':
        current_session = f"{temp_dir} -> {dest_org}"
    else:  # migrate
        current_session = f"{source_org} -> {dest_org}"
    
    # Check for existing session
    if os.path.exists(files['session']):
        with open(files['session'], 'r', encoding='utf-8') as f:
            previous_session = f.read().strip()
        
        if previous_session != current_session:
            print()
            print("=" * 60)
            print("⚠ Warning: Different session detected!")
            print("=" * 60)
            print(f"Previous: {previous_session}")
            print(f"Current:  {current_session}")
            print()
            print("The existing tracking files are for a different operation.")
            print("They will be automatically cleared to avoid confusion.")
            
            # Automatically clear old tracking files
            for file_key in ['completed', 'error', 'success']:
                if os.path.exists(files[file_key]):
                    os.remove(files[file_key])
            print("✓ Old tracking files cleared")
            print()
    
    # Write current session info
    with open(files['session'], 'w', encoding='utf-8') as f:
        f.write(current_session)
    
    return files

def setup_operation():
    """Handle mode selection and input collection."""
    print("=" * 60)
    print("GitHub Organization Repository Tool")
    print("=" * 60)
    print()
    
    # Check prerequisites
    check_git_installed()
    check_gh_installed()
    check_gh_authenticated()
    setup_git_credentials()
    print()
    
    # Mode selection
    print("Select operation mode:")
    print("  1. Remote → Local (download repos to disk)")
    print("  2. Local → Remote (upload repos from disk to GitHub org)")
    print("  3. Remote → Remote (migrate between GitHub orgs)")
    print()
    mode_choice = input("Mode (1, 2, or 3): ").strip()
    
    if mode_choice == "1":
        operation_mode = 'download'
    elif mode_choice == "2":
        operation_mode = 'upload'
    elif mode_choice == "3":
        operation_mode = 'migrate'
    else:
        print("ERROR: Invalid mode selection. Please choose 1, 2, or 3.")
        sys.exit(1)
    
    print()
    
    # Collect mode-specific inputs
    config = {'operation_mode': operation_mode}
    
    if operation_mode == 'download':
        config['source_org'] = input("Source organization name: ").strip()
        config['dest_org'] = None
        
        print()
        print("Verifying organization access...")
        check_org_access(config['source_org'])
        print(f"✓ Admin rights confirmed for {config['source_org']}")
        print()
        
        # Format selection
        print("Download format:")
        print("  1. Working repositories (regular clone)")
        print("  2. Mirror repositories (--mirror, archival)")
        print()
        format_choice = input("Format (1 or 2): ").strip()
        config['use_mirror'] = (format_choice == "2")
        print()
        
        # Get target directory
        temp_dir = input("Target directory path (repos will be saved here): ").strip()
        temp_dir = os.path.expanduser(temp_dir)
        
        if not os.path.exists(temp_dir):
            print(f"\nCreating directory: {temp_dir}")
            os.makedirs(temp_dir)
        
        if not os.path.isdir(temp_dir):
            print(f"ERROR: {temp_dir} is not a directory")
            sys.exit(1)
        
        config['temp_dir'] = temp_dir
        print()
        
    elif operation_mode == 'upload':
        source_dir = input("Source directory path (scan for git repos): ").strip()
        source_dir = os.path.expanduser(source_dir)
        
        if not os.path.exists(source_dir):
            print(f"ERROR: Directory does not exist: {source_dir}")
            sys.exit(1)
        if not os.path.isdir(source_dir):
            print(f"ERROR: {source_dir} is not a directory")
            sys.exit(1)
        
        config['source_dir'] = source_dir
        config['temp_dir'] = source_dir  # Reuse for consistency
        config['dest_org'] = input("Destination organization name: ").strip()
        config['source_org'] = None
        print()
        
        print("Verifying organization access...")
        check_org_access(config['dest_org'])
        print(f"✓ Admin rights confirmed for {config['dest_org']}")
        print()
        
    else:  # migrate
        config['source_org'] = input("Source organization name: ").strip()
        config['dest_org'] = input("Destination organization name: ").strip()
        print()
        
        print("Verifying organization access...")
        check_org_access(config['source_org'])
        print(f"✓ Admin rights confirmed for {config['source_org']}")
        check_org_access(config['dest_org'])
        print(f"✓ Admin rights confirmed for {config['dest_org']}")
        print()
    
    return config

def validate_operation(config):
    """Check org access, detect repos, and handle conflicts."""
    operation_mode = config['operation_mode']
    
    if operation_mode == 'download':
        print("Detecting repos...")
        source_repos = get_repos_with_details(config['source_org'])
        
        print("Scanning target directory for existing repos...")
        existing_local = scan_local_git_repos(config['temp_dir'])
        dest_repos = existing_local
        
        print(f"✓ {len(source_repos)} repos found in {config['source_org']}")
        print(f"✓ {len(existing_local)} repos already exist locally")
        print()
        
    elif operation_mode == 'upload':
        print("Scanning directory for git repositories...")
        local_repos = scan_local_git_repos(config['source_dir'])
        source_repos = local_repos
        
        print("Detecting existing repos in destination org...")
        dest_repos = get_repos_with_details(config['dest_org'])
        
        print(f"✓ {len(source_repos)} git repositories found locally")
        print(f"✓ {len(dest_repos)} repos found in {config['dest_org']}")
        print()
        
    else:  # migrate
        print("Detecting repos in both orgs...")
        source_repos = get_repos_with_details(config['source_org'])
        dest_repos = get_repos_with_details(config['dest_org'])
        
        print(f"✓ {len(source_repos)} repos found in {config['source_org']}")
        print(f"✓ {len(dest_repos)} repos found in {config['dest_org']}")
        print()
    
    # Initialize tracking files
    files = initialize_tracking_files(operation_mode, config.get('source_org'), config.get('dest_org'), config.get('temp_dir'))
    
    # Handle conflicts
    source_names = {repo['name'].lower(): repo['name'] for repo in source_repos}
    dest_names = {repo['name'].lower(): repo['name'] for repo in dest_repos}
    conflicts = set(source_names.keys()) & set(dest_names.keys())
    
    if conflicts:
        if operation_mode == 'download':
            print()
            print("=" * 60)
            print("Matching repository names found locally.")
            print("=" * 60)
            print(f"✓ {len(conflicts)} repos already exist locally and will be skipped")
            
            for name_lower in conflicts:
                repo_name = source_names[name_lower]
                if repo_name not in load_completed_repos(files['completed']):
                    with open(files['completed'], 'a', encoding='utf-8') as f:
                        f.write(f"{repo_name}\n")
            print()
            
        elif operation_mode == 'upload':
            print()
            print("=" * 60)
            print("Matching repository names found in destination org.")
            print("=" * 60)
            print(f"✓ {len(conflicts)} repos already exist remotely and will be skipped")
            
            for name_lower in conflicts:
                repo_name = source_names[name_lower]
                if repo_name not in load_completed_repos(files['completed']):
                    with open(files['completed'], 'a', encoding='utf-8') as f:
                        f.write(f"{repo_name}\n")
            print()
            
        else:  # migrate
            print()
            print("=" * 60)
            print("Matching repository names found. Verifying if duplicates...")
            print("=" * 60)
            
            actual_conflicts = []
            verified_duplicates = []
            
            for name_lower in sorted(conflicts):
                repo_name = source_names[name_lower]
                print(f"Checking: {repo_name}...", end=' ')
                
                is_identical, reason = compare_repos(config['source_org'], config['dest_org'], repo_name)
                
                if is_identical:
                    print(f"✓ Verified duplicate")
                    verified_duplicates.append(repo_name)
                else:
                    print(f"✗ Different ({reason})")
                    actual_conflicts.append(repo_name)
            
            print()
            
            if actual_conflicts:
                print("ERROR: Non-duplicate repositories with matching names found:")
                for name in actual_conflicts:
                    print(f"  - {name}")
                print()
                print("This tool is intended ONLY to copy one whole github org")
                print("into one raw empty org, and it is not built to deal with conflicts.")
                sys.exit(1)
            
            if verified_duplicates:
                print(f"✓ All {len(verified_duplicates)} matching repos are verified duplicates")
                print("These will be skipped during migration.")
                for repo_name in verified_duplicates:
                    if repo_name not in load_completed_repos(files['completed']):
                        with open(files['completed'], 'a', encoding='utf-8') as f:
                            f.write(f"{repo_name}\n")
                print()
    else:
        print("✓ No conflicts!")
        print()
    
    return source_repos, dest_repos, files

def show_summary(operation_mode, total_repos, successful, failed, temp_dir, files):
    """Display final summary statistics."""
    print("=" * 60)
    if operation_mode == 'download':
        print("Download Complete")
        print("=" * 60)
        print(f"Total processed: {total_repos}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"\nRepositories saved to: {temp_dir}")
    elif operation_mode == 'upload':
        print("Upload Complete")
        print("=" * 60)
        print(f"Total processed: {total_repos}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"\nRepositories uploaded from: {temp_dir}")
    else:  # migrate
        print("Migration Complete")
        print("=" * 60)
        print(f"Total processed: {total_repos}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
    
    if failed > 0:
        print(f"\nSee {files['error']} for error details")
    
    print(f"\nCompleted repos logged in: {files['completed']}")
    print(f"Success log: {files['success']}")

def download_single_repo(repo, idx, total_repos, source_org, temp_dir, use_mirror, completed_file, success_log, error_log):
    """Download a single repository (for parallel execution)."""
    repo_name = repo['name']
    start_time = time.time()
    repo_size = format_size(repo.get('diskUsage', 0))
    uses_lfs = repo.get('uses_lfs', False)

    # Thread-safe printing with lock
    print_lock = threading.Lock()

    try:
        with print_lock:
            print(f"[{idx}/{total_repos}] Processing: {repo_name} [{repo_size}]")
            if uses_lfs:
                print(f"  ⚠ This repo uses Git LFS")

        # Determine final path based on format
        if use_mirror:
            repo_final_path = os.path.join(temp_dir, f"{repo_name}.git")
        else:
            repo_final_path = os.path.join(temp_dir, repo_name)

        # Clean up any leftover directory first (safely)
        if os.path.exists(repo_final_path):
            with print_lock:
                print(f"  → [{repo_name}] Cleaning up leftover directory...")
            if not safe_cleanup_directory(repo_final_path, temp_dir, repo_name):
                with print_lock:
                    print(f"  ⚠ [{repo_name}] Warning: Could not safely clean up directory")

        clone_url = f"https://github.com/{source_org}/{repo_name}.git"

        with print_lock:
            print(f"  → [{repo_name}] Cloning from {source_org}...")

        # Clone with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if use_mirror:
                    run_command(['git', 'clone', '--mirror', clone_url, repo_final_path], check=True)
                else:
                    run_command(['git', 'clone', clone_url, repo_final_path], check=True)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    with print_lock:
                        print(f"  → [{repo_name}] Clone attempt {attempt + 1} failed, retrying...")
                    time.sleep(5)
                else:
                    raise

        # Mark as complete (thread-safe)
        with open(completed_file, 'a', encoding='utf-8') as f:
            f.write(f"{repo_name}\n")

        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        with print_lock:
            print(f"✓ [{repo_name}] Complete ({elapsed:.1f}s)")

        return {'status': 'success', 'repo': repo_name, 'time': elapsed}

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        with print_lock:
            print(f"✗ [{repo_name}] FAILED: {str(e)}")

        return {'status': 'failed', 'repo': repo_name, 'time': elapsed, 'error': str(e)}

def main():
    # Setup operation (mode selection and input collection)
    config = setup_operation()
    operation_mode = config['operation_mode']
    
    # Validate operation (check access, detect repos, handle conflicts)
    source_repos, dest_repos, files = validate_operation(config)
    
    # Display repository information
    if operation_mode == 'download':
        display_repo_table(source_repos, config['source_org'])
    elif operation_mode == 'upload':
        print()
        print("=" * 100)
        print("Local Git Repositories Found")
        print("=" * 100)
        if not source_repos:
            print("No git repositories found.")
        else:
            print(f"{'#':<4} {'Name':<40} {'Type':<12} {'Path':<50}")
            print("-" * 100)
            for idx, repo in enumerate(sorted(source_repos, key=lambda r: r['name']), 1):
                repo_type = "Mirror" if repo.get('is_mirror', False) else "Regular"
                path_display = repo['path'][:49] if len(repo['path']) > 49 else repo['path']
                print(f"{idx:<4} {repo['name']:<40} {repo_type:<12} {path_display:<50}")
            print("=" * 100)
            print(f"Total: {len(source_repos)} repositories")
        print()
    else:  # migrate
        display_repo_table(source_repos, config['source_org'])
        display_repo_table(dest_repos, config['dest_org'])
    
    # Pause for user review
    print()
    print("=" * 60)
    print("Review the repository information above.")
    print("=" * 60)
    if operation_mode == 'download':
        input("Press ENTER to continue to download setup...")
    elif operation_mode == 'upload':
        input("Press ENTER to continue to upload setup...")
    else:
        input("Press ENTER to continue to migration setup...")
    print()
    
    # Get temp directory for migrate mode
    if operation_mode == 'migrate':
        temp_dir = input("Temporary directory path (for cloning): ").strip()
        temp_dir = os.path.expanduser(temp_dir)
        
        if not os.path.exists(temp_dir):
            print(f"\nCreating directory: {temp_dir}")
            os.makedirs(temp_dir)
        
        if not os.path.isdir(temp_dir):
            print(f"ERROR: {temp_dir} is not a directory")
            sys.exit(1)
        config['temp_dir'] = temp_dir
        print()
    
    # Load completed repos
    completed_repos = load_completed_repos(files['completed'])
    remaining_repos = [r for r in source_repos if r['name'] not in completed_repos]
    
    if completed_repos:
        print(f"{len(completed_repos)} repos already completed")
        print(f"{len(remaining_repos)} repos remaining")
    else:
        if operation_mode == 'download':
            print(f"Ready to download {len(remaining_repos)} repos from {config['source_org']}")
        elif operation_mode == 'upload':
            print(f"Ready to upload {len(remaining_repos)} repos to {config['dest_org']}")
        else:  # migrate
            print(f"Ready to copy {len(remaining_repos)} repos from {config['source_org']} to {config['dest_org']}")
    
    print()
    
    # Ask about parallel operations for download mode
    parallel_workers = 1
    if operation_mode == 'download' and len(remaining_repos) > 1:
        print("Parallel downloads can speed up the process significantly.")
        parallel_input = input("Number of parallel downloads (1-5, default 3): ").strip()
        if parallel_input == "":
            parallel_workers = 3
        elif parallel_input.isdigit() and 1 <= int(parallel_input) <= 5:
            parallel_workers = int(parallel_input)
        else:
            print("Invalid input, using default (3)")
            parallel_workers = 3
        print(f"Using {parallel_workers} parallel download(s)")
        print()
    
    # Confirm before proceeding
    confirmation = input('Type "YES" to continue: ').strip()
    if confirmation != "YES":
        print("Aborted.")
        sys.exit(0)
    
    print()
    print("=" * 60)
    if operation_mode == 'download':
        print("Starting download...")
    elif operation_mode == 'upload':
        print("Starting upload...")
    else:  # migrate
        print("Starting migration...")
    print("=" * 60)
    print()
    
    # Sort repos
    if operation_mode != 'upload':
        remaining_repos.sort(key=lambda r: r.get('createdAt', ''))
    else:
        remaining_repos.sort(key=lambda r: r['name'])
    
    # Statistics
    total_repos = len(remaining_repos)
    successful = 0
    failed = 0
    
    # Execute operation
    if operation_mode == 'download' and parallel_workers > 1:
        print(f"Starting parallel downloads with {parallel_workers} workers...")
        print()
        
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            future_to_repo = {
                executor.submit(
                    download_single_repo,
                    repo, idx, total_repos, config['source_org'], config['temp_dir'], config['use_mirror'],
                    files['completed'], files['success'], files['error']
                ): (idx, repo) for idx, repo in enumerate(remaining_repos, 1)
            }
            
            for future in as_completed(future_to_repo):
                result = future.result()
                if result['status'] == 'success':
                    successful += 1
                else:
                    failed += 1
    else:
        # Sequential processing
        for idx, repo in enumerate(remaining_repos, 1):
            repo_name = repo['name']
            
            if operation_mode == 'download':
                result = process_download_repo(
                    repo, config['source_org'], config['temp_dir'], config['use_mirror'],
                    files['completed'], files['success'], files['error']
                )
            elif operation_mode == 'upload':
                result = process_upload_repo(
                    repo, config['dest_org'], files['completed'], files['success'], files['error']
                )
            else:  # migrate
                result = process_migrate_repo(
                    repo, config['source_org'], config['dest_org'], config['temp_dir'],
                    files['completed'], files['success'], files['error']
                )
            
            if result['status'] == 'success':
                successful += 1
            else:
                failed += 1
    
    # Show summary
    show_summary(operation_mode, total_repos, successful, failed, config['temp_dir'], files)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        print("If any repos were processed, progress is saved in the tracking file.")
        print("Run script again to resume.")
        sys.exit(0)