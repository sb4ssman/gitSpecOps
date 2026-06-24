"""
tracking
========

Resume state for the duplicator. Each operation mode keeps its own set of run files under
RUNS_DIR: completed-repo list, error log, success log, and a session marker. If a new run
targets a different source/destination than the last, the stale per-mode files are cleared
so resume can't mix two unrelated operations.
"""

import os

from gh_common import RUNS_DIR


def get_tracking_files(operation_mode):
    """Return the tracking file paths for an operation mode (creating RUNS_DIR)."""
    if operation_mode == 'download':
        names = {
            'completed': 'downloaded_repos.txt',
            'error': 'download_errors.txt',
            'success': 'download_log.txt',
            'session': 'download_session.txt'
        }
    elif operation_mode == 'upload':
        names = {
            'completed': 'uploaded_repos.txt',
            'error': 'upload_errors.txt',
            'success': 'upload_log.txt',
            'session': 'upload_session.txt'
        }
    else:  # migrate
        names = {
            'completed': 'completed_repos.txt',
            'error': 'migration_errors.txt',
            'success': 'migration_log.txt',
            'session': 'migration_session.txt'
        }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return {key: RUNS_DIR / name for key, name in names.items()}


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

    print(f"Run files: {RUNS_DIR}")

    return files


def load_completed_repos(filename):
    """Load the set of completed repo names from a tracking file."""
    if not os.path.exists(filename):
        return set()
    with open(filename, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())
