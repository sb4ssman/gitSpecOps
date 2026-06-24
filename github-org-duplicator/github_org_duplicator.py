#!/usr/bin/env python3
"""
GitHub Organization Repository Tool

Interactive, confirmation-driven copying of whole GitHub organizations:
  1. Remote -> Local   (download an org's repos to disk)
  2. Local  -> Remote  (upload local repos into an org)
  3. Remote -> Remote  (migrate one org into another)

This file is the orchestrator only. The real work lives in sibling modules:
  gh_common    shared subprocess/print/format helpers
  gh_remote    everything that talks to GitHub via `gh`
  local_repos  on-disk repo discovery and safe cleanup
  tracking     resume state / run files
  operations   the per-repo download/upload/migrate workers

Requires: git, and gh CLI authenticated (gh auth login).
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from gh_common import RUNS_DIR, format_size, prompt_input
from gh_remote import (
    check_gh_authenticated,
    check_gh_installed,
    check_git_installed,
    check_org_access,
    compare_repos,
    get_repos_with_details,
    setup_git_credentials,
)
from local_repos import scan_local_git_repos
from operations import download_single_repo, process_migrate_repo, process_upload_repo
from tracking import initialize_tracking_files, load_completed_repos


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
    mode_choice = prompt_input("Mode (1, 2, or 3): ")

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
        config['source_org'] = prompt_input("Source organization name: ")
        config['dest_org'] = None

        print()
        print("Verifying organization access...")
        check_org_access(config['source_org'])
        print(f"✓ Access confirmed for {config['source_org']}")
        print()

        # Format selection
        print("Download format:")
        print("  1. Working repositories (regular clone)")
        print("  2. Mirror repositories (--mirror, archival)")
        print()
        format_choice = prompt_input("Format (1 or 2): ")
        config['use_mirror'] = (format_choice == "2")
        print()

        # Get target directory
        temp_dir = prompt_input("Target directory path (repos will be saved here): ")
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
        source_dir = prompt_input("Source directory path (scan for git repos): ")
        source_dir = os.path.expanduser(source_dir)

        if not os.path.exists(source_dir):
            print(f"ERROR: Directory does not exist: {source_dir}")
            sys.exit(1)
        if not os.path.isdir(source_dir):
            print(f"ERROR: {source_dir} is not a directory")
            sys.exit(1)

        config['source_dir'] = source_dir
        config['temp_dir'] = source_dir  # Reuse for consistency
        config['dest_org'] = prompt_input("Destination organization name: ")
        config['source_org'] = None
        print()

        print("Verifying organization access...")
        check_org_access(config['dest_org'])
        print(f"✓ Read access confirmed for {config['dest_org']} (write access is verified when repos are created)")
        print()

    else:  # migrate
        config['source_org'] = prompt_input("Source organization name: ")
        config['dest_org'] = prompt_input("Destination organization name: ")
        print()

        print("Verifying organization access...")
        check_org_access(config['source_org'])
        print(f"✓ Access confirmed for {config['source_org']}")
        check_org_access(config['dest_org'])
        print(f"✓ Read access confirmed for {config['dest_org']} (write access is verified when repos are created)")
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
                    print("✓ Verified duplicate")
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


def main():
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("GitHub Organization Repository Tool")
        print()
        print("Usage:")
        print("  uv run python github-org-duplicator\\github_org_duplicator.py")
        print("  github-org-duplicator\\duplicate-github-org.bat")
        print()
        print("Modes:")
        print("  1. Remote -> Local download")
        print("  2. Local -> Remote upload")
        print("  3. Remote -> Remote migration")
        print()
        print(f"Run files: {RUNS_DIR}")
        return

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
        prompt_input("Press ENTER to continue to download setup...")
    elif operation_mode == 'upload':
        prompt_input("Press ENTER to continue to upload setup...")
    else:
        prompt_input("Press ENTER to continue to migration setup...")
    print()

    # Get temp directory for migrate mode
    if operation_mode == 'migrate':
        temp_dir = prompt_input("Temporary directory path (for cloning): ")
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
        parallel_input = prompt_input("Number of parallel downloads (1-5, default 3): ")
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
    confirmation = prompt_input('Type "YES" to continue: ')
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

    # Execute operation. Download always runs through the pool (workers may be 1); upload and
    # migrate are sequential because they create remote repos and we don't want to race those.
    if operation_mode == 'download':
        if parallel_workers > 1:
            print(f"Starting parallel downloads with {parallel_workers} workers...")
            print()
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            futures = [
                executor.submit(
                    download_single_repo,
                    repo, idx, total_repos, config['source_org'], config['temp_dir'], config['use_mirror'],
                    files['completed'], files['success'], files['error']
                )
                for idx, repo in enumerate(remaining_repos, 1)
            ]
            for future in as_completed(futures):
                if future.result()['status'] == 'success':
                    successful += 1
                else:
                    failed += 1
    else:
        # Sequential processing for upload / migrate.
        for idx, repo in enumerate(remaining_repos, 1):
            if operation_mode == 'upload':
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
