"""
operations
==========

The per-repository workers for each mode: download (clone to disk, retried, parallel-safe),
upload (create the dest repo if needed, push every non-PR ref), and migrate (mirror-clone
from source, create dest, push, clean up). Each returns a {'status': 'success'|'failed', ...}
dict and records progress to the tracking files; failures are caught and reported, never fatal.
"""

import os
import random
import time

from gh_common import PRINT_LOCK, CommandTimeout, format_size, log_message, run_command
from gh_remote import create_repo, ensure_repo
from local_repos import safe_cleanup_directory

RETRY_ATTEMPTS = 3


def _retry_backoff(attempt):
    """Seconds to wait before the next attempt: 5s, 10s, ... plus jitter so parallel
    workers hitting the same transient failure don't retry in lockstep."""
    return 5 * (attempt + 1) + random.uniform(0, 3)


def download_single_repo(repo, idx, total_repos, source_org, temp_dir, use_mirror, completed_file, success_log, error_log):
    """Download a single repository. Safe to run from a thread pool."""
    repo_name = repo['name']
    start_time = time.time()
    repo_size = format_size(repo.get('diskUsage', 0))
    uses_lfs = repo.get('uses_lfs', False)

    try:
        with PRINT_LOCK:
            print(f"[{idx}/{total_repos}] Processing: {repo_name} [{repo_size}]")
            if uses_lfs:
                print("  ⚠ This repo uses Git LFS")

        # Determine final path based on format
        if use_mirror:
            repo_final_path = os.path.join(temp_dir, f"{repo_name}.git")
        else:
            repo_final_path = os.path.join(temp_dir, repo_name)

        # Clean up any leftover directory first (safely)
        if os.path.exists(repo_final_path):
            with PRINT_LOCK:
                print(f"  → [{repo_name}] Cleaning up leftover directory...")
            if not safe_cleanup_directory(repo_final_path, temp_dir, repo_name):
                with PRINT_LOCK:
                    print(f"  ⚠ [{repo_name}] Warning: Could not safely clean up directory")

        clone_url = f"https://github.com/{source_org}/{repo_name}.git"

        with PRINT_LOCK:
            print(f"  → [{repo_name}] Cloning from {source_org}...")

        # Clone with retries
        clone_cmd = ['git', 'clone', '--mirror', clone_url, repo_final_path] if use_mirror \
            else ['git', 'clone', clone_url, repo_final_path]
        for attempt in range(RETRY_ATTEMPTS):
            try:
                run_command(clone_cmd, check=True)
                break
            except CommandTimeout:
                raise  # a hung clone won't un-hang on a retry
            except RuntimeError as exc:
                if attempt >= RETRY_ATTEMPTS - 1:
                    raise
                with PRINT_LOCK:
                    print(f"  → [{repo_name}] clone attempt {attempt + 1} failed "
                          f"({str(exc).splitlines()[-1][:120]}); retrying...")
                # A partial clone left behind will make the retry fail on "directory exists".
                if os.path.exists(repo_final_path):
                    safe_cleanup_directory(repo_final_path, temp_dir, repo_name)
                time.sleep(_retry_backoff(attempt))

        # Mark as complete
        with PRINT_LOCK:
            with open(completed_file, 'a', encoding='utf-8') as f:
                f.write(f"{repo_name}\n")

        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        with PRINT_LOCK:
            print(f"✓ [{repo_name}] Complete ({elapsed:.1f}s)")

        return {'status': 'success', 'repo': repo_name, 'time': elapsed}

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        with PRINT_LOCK:
            print(f"✗ [{repo_name}] FAILED: {str(e)}")

        return {'status': 'failed', 'repo': repo_name, 'time': elapsed, 'error': str(e)}


def process_upload_repo(repo, dest_org, completed_file, success_log, error_log):
    """Process a single repository upload."""
    repo_name = repo['name']
    repo_path = repo['path']
    start_time = time.time()
    is_mirror = repo.get('is_mirror', False)

    print(f"Processing: {repo_name}")
    if is_mirror:
        print("  → Mirror repository")

    try:
        # Step 1: Create repo in dest org (default to private)
        print(f"  → Creating in {dest_org}...")
        if not ensure_repo(dest_org, repo_name, private=True):
            print("  → Repository already exists, skipping creation")

        # Step 2: Push all refs to dest org (excluding pull request refs)
        print(f"  → Pushing to {dest_org}...")
        push_url = f"https://github.com/{dest_org}/{repo_name}.git"

        max_retries = RETRY_ATTEMPTS
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
            except RuntimeError:
                if attempt < max_retries - 1:
                    print(f"  → Push attempt {attempt + 1} failed, retrying...")
                    time.sleep(_retry_backoff(attempt))
                else:
                    raise

        # Mark as complete
        with PRINT_LOCK:
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
        print("  ⚠ This repo uses Git LFS")

    repo_temp_path = os.path.join(temp_dir, repo_name)

    try:
        # Step 1: Clone from source org
        print(f"  → Cloning from {source_org}...")

        # Clean up any leftover temp directory first (safely)
        if os.path.exists(repo_temp_path):
            print("  → Cleaning up leftover temp directory...")
            if not safe_cleanup_directory(repo_temp_path, temp_dir, repo_name):
                print("  ⚠ Warning: Could not safely clean up temp directory")
                print("  → Attempting clone anyway...")

        clone_url = f"https://github.com/{source_org}/{repo_name}.git"

        # Retry logic for clone
        max_retries = RETRY_ATTEMPTS
        for attempt in range(max_retries):
            try:
                run_command(['git', 'clone', '--mirror', clone_url, repo_temp_path], check=True)
                break
            except RuntimeError:
                if attempt < max_retries - 1:
                    print(f"  → Clone attempt {attempt + 1} failed, retrying...")
                    if os.path.exists(repo_temp_path):
                        safe_cleanup_directory(repo_temp_path, temp_dir, repo_name)
                    time.sleep(_retry_backoff(attempt))
                else:
                    raise

        # Step 2: Create repo in dest org
        print(f"  → Creating in {dest_org}...")
        create_repo(dest_org, repo_name, private=is_private, description=description)

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
            except RuntimeError:
                if attempt < max_retries - 1:
                    print(f"  → Push attempt {attempt + 1} failed, retrying...")
                    time.sleep(_retry_backoff(attempt))
                else:
                    raise

        # Step 4: Clean up temp directory (safely)
        print("  → Cleaning up...")
        if os.path.exists(repo_temp_path):
            safe_cleanup_directory(repo_temp_path, temp_dir, repo_name)

        # Step 5: Mark as complete
        with PRINT_LOCK:
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
