"""
operations
==========

The per-repository workers for each mode: download (clone to disk, retried, parallel-safe),
upload (create the dest repo if needed, push every non-PR ref), and migrate (mirror-clone
from source, create dest, push, clean up). Each returns a {'status': 'success'|'failed', ...}
dict and records progress to the tracking files; failures are caught and reported, never fatal.
Import workers from Special._org_duplicator.operations; importing never starts a Git operation.
"""

import os
import random
import time

from Basic._confirm import prompt_input
from Basic._console import PRINT_LOCK, format_size
from Basic._station import say, step_line
from Basic._providers.github import create_repo, ensure_repo
from Basic._run import CommandTimeout, run_checked
from Special._org_duplicator.local_repos import safe_cleanup_directory
from Special._org_duplicator.tracking import log_message

RETRY_ATTEMPTS = 3

# Upper bound on a single git operation. Large clones are legitimately slow, but a clone
# that has made no progress for this long is hung (dead connection, a server that stopped
# responding) and must not block a worker thread forever.
GIT_OP_TIMEOUT_SECONDS = 3600


def _retry_backoff(attempt):
    """Seconds to wait before the next attempt: 5s, 10s, ... plus jitter so parallel
    workers hitting the same transient failure don't retry in lockstep."""
    return 5 * (attempt + 1) + random.uniform(0, 3)


def _is_empty_dir(path):
    try:
        return os.path.isdir(path) and not os.listdir(path)
    except OSError:
        return False


def _undo_own_clone(path, parent, repo_name, keep_empty_folder):
    """Remove what this run cloned at `path`; put back the empty folder if the user had one.

    A half-finished clone left in place has a `.git`, so the next batch run would count it as
    already downloaded and skip it for good.
    """
    if os.path.exists(path) and not _is_empty_dir(path):
        safe_cleanup_directory(path, parent, repo_name)
    if keep_empty_folder and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def download_single_repo(repo, idx, total_repos, source_org, temp_dir, use_mirror, completed_file, success_log, error_log):
    """Download a single repository. Safe to run from a thread pool.

    The destination may be absent or an empty folder (git clones into either). Anything else
    already there is refused and left untouched.
    """
    repo_name = repo['name']
    start_time = time.time()
    repo_size = format_size(repo.get('diskUsage', 0))
    uses_lfs = repo.get('uses_lfs', False)
    repo_final_path = None
    was_empty_folder = False
    cloning = False

    try:
        # Determine final path based on format
        if use_mirror:
            repo_final_path = os.path.join(temp_dir, f"{repo_name}.git")
        else:
            repo_final_path = os.path.join(temp_dir, repo_name)

        # Anything already here was not made by this run. The batch skips folders discovery
        # recognizes as repositories, so what remains is the user's own folder -- possibly the
        # only copy of something. An empty one is a prepared destination; anything else is
        # never deleted as a "leftover", and this repository fails.
        if os.path.exists(repo_final_path):
            if not _is_empty_dir(repo_final_path):
                raise RuntimeError(f"{repo_final_path} already exists and is not empty; it was left "
                                   "untouched (move it aside, or empty it, to download here)")
            was_empty_folder = True

        clone_url = f"https://github.com/{source_org}/{repo_name}.git"

        # Clone with retries
        clone_cmd = ['git', 'clone', '--mirror', clone_url, repo_final_path] if use_mirror \
            else ['git', 'clone', clone_url, repo_final_path]
        cloning = True  # from here, whatever is at repo_final_path is this run's own
        for attempt in range(RETRY_ATTEMPTS):
            try:
                run_checked(clone_cmd, timeout=GIT_OP_TIMEOUT_SECONDS)
                break
            except CommandTimeout:
                raise  # a hung clone won't un-hang on a retry
            except RuntimeError as exc:
                if attempt >= RETRY_ATTEMPTS - 1:
                    raise
                with PRINT_LOCK:
                    say(f"        {repo_name}: clone attempt {attempt + 1} failed "
                        f"({str(exc).splitlines()[-1][:80]}); retrying", "detail")
                # A partial clone left behind will make the retry fail on "directory exists".
                _undo_own_clone(repo_final_path, temp_dir, repo_name, was_empty_folder)
                time.sleep(_retry_backoff(attempt))
        cloning = False

        # Mark as complete
        with PRINT_LOCK:
            with open(completed_file, 'a', encoding='utf-8') as f:
                f.write(f"{repo_name}\n")

        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        with PRINT_LOCK:
            step_line(idx, total_repos, repo_name, "ok", elapsed,
                      repo_size + ("; uses Git LFS" if uses_lfs else ""))

        return {'status': 'success', 'repo': repo_name, 'time': elapsed}

    except Exception as e:
        if cloning:
            _undo_own_clone(repo_final_path, temp_dir, repo_name, was_empty_folder)
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        with PRINT_LOCK:
            step_line(idx, total_repos, repo_name, "FAILED", elapsed, str(e).splitlines()[-1][:120] if str(e) else "")

        return {'status': 'failed', 'repo': repo_name, 'time': elapsed, 'error': str(e)}


def process_upload_repo(repo, dest_org, completed_file, success_log, error_log, idx=1, total=1):
    """Process a single repository upload; one step line when it finishes."""
    repo_name = repo['name']
    repo_path = repo['path']
    start_time = time.time()
    is_mirror = repo.get('is_mirror', False)

    existed = False
    try:
        # Step 1: Create repo in dest org (default to private)
        existed = not ensure_repo(dest_org, repo_name, private=True)

        # Step 2: Push all refs to dest org (excluding pull request refs)
        push_url = f"https://github.com/{dest_org}/{repo_name}.git"

        max_retries = RETRY_ATTEMPTS
        for attempt in range(max_retries):
            try:
                # Get list of all refs
                result = run_checked(
                    ['git', '-C', repo_path, 'for-each-ref', '--format=%(refname)', 'refs/'], timeout=GIT_OP_TIMEOUT_SECONDS)

                # Filter out pull request refs
                all_refs = result.stdout.strip().split('\n')
                good_refs = [ref for ref in all_refs if ref and not ref.startswith('refs/pull/')]

                # Push only the good refs
                if good_refs:
                    run_checked(['git', '-C', repo_path, 'push', push_url] + good_refs, timeout=GIT_OP_TIMEOUT_SECONDS)
                break
            except CommandTimeout:
                raise  # a hung command won't un-hang on a retry
            except RuntimeError:
                if attempt < max_retries - 1:
                    say(f"        {repo_name}: push attempt {attempt + 1} failed; retrying", "detail")
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
        step_line(idx, total, repo_name, "ok", elapsed,
                  ("mirror; " if is_mirror else "") + ("pushed to the existing repository" if existed
                                                       else f"created in {dest_org}, private"))
        return {'status': 'success', 'elapsed': elapsed}

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        step_line(idx, total, repo_name, "FAILED", elapsed, str(e).splitlines()[-1][:120] if str(e) else "")
        return {'status': 'failed', 'elapsed': elapsed, 'error': str(e)}


def process_migrate_repo(repo, source_org, dest_org, temp_dir, completed_file, success_log, error_log,
                         idx=1, total=1):
    """Process a single repository migration; one step line when it finishes."""
    repo_name = repo['name']
    start_time = time.time()
    is_private = repo['isPrivate']
    description = repo.get('description', '') or ''
    uses_lfs = repo.get('uses_lfs', False)
    repo_size = format_size(repo.get('diskUsage', 0))

    repo_temp_path = os.path.join(temp_dir, repo_name)
    created = False  # cleanup may remove only a mirror this run cloned
    was_empty_folder = False

    try:
        # Step 1: Clone from source org

        # A folder already at the working path was not made by this run: an empty one is used
        # (and left empty afterwards); anything else is refused, never deleted.
        if os.path.exists(repo_temp_path):
            if not _is_empty_dir(repo_temp_path):
                raise RuntimeError(f"{repo_temp_path} already exists and is not empty; it was "
                                   "left untouched (choose an empty working folder)")
            was_empty_folder = True
        created = True

        clone_url = f"https://github.com/{source_org}/{repo_name}.git"

        # Retry logic for clone
        max_retries = RETRY_ATTEMPTS
        for attempt in range(max_retries):
            try:
                run_checked(['git', 'clone', '--mirror', clone_url, repo_temp_path], timeout=GIT_OP_TIMEOUT_SECONDS)
                break
            except CommandTimeout:
                raise  # a hung command won't un-hang on a retry
            except RuntimeError:
                if attempt < max_retries - 1:
                    say(f"        {repo_name}: clone attempt {attempt + 1} failed; retrying", "detail")
                    _undo_own_clone(repo_temp_path, temp_dir, repo_name, was_empty_folder)
                    time.sleep(_retry_backoff(attempt))
                else:
                    raise

        # Step 2: Create repo in dest org
        create_repo(dest_org, repo_name, private=is_private, description=description)

        # Step 3: Push to dest org (excluding pull request refs)
        push_url = f"https://github.com/{dest_org}/{repo_name}.git"

        # Retry logic for push
        for attempt in range(max_retries):
            try:
                # First, get list of all refs
                result = run_checked(
                    ['git', '-C', repo_temp_path, 'for-each-ref', '--format=%(refname)', 'refs/'], timeout=GIT_OP_TIMEOUT_SECONDS)

                # Filter out pull request refs
                all_refs = result.stdout.strip().split('\n')
                good_refs = [ref for ref in all_refs if ref and not ref.startswith('refs/pull/')]

                # Push only the good refs
                if good_refs:
                    run_checked(['git', '-C', repo_temp_path, 'push', push_url] + good_refs, timeout=GIT_OP_TIMEOUT_SECONDS)
                break
            except CommandTimeout:
                raise  # a hung command won't un-hang on a retry
            except RuntimeError:
                if attempt < max_retries - 1:
                    say(f"        {repo_name}: push attempt {attempt + 1} failed; retrying", "detail")
                    time.sleep(_retry_backoff(attempt))
                else:
                    raise

        # Step 4: Clean up temp directory (safely)
        _undo_own_clone(repo_temp_path, temp_dir, repo_name, was_empty_folder)

        # Step 5: Mark as complete
        with PRINT_LOCK:
            with open(completed_file, 'a', encoding='utf-8') as f:
                f.write(f"{repo_name}\n")

        elapsed = time.time() - start_time
        success_msg = f"✓ {repo_name} complete (took {elapsed:.1f}s)"
        log_message(success_msg, success_log)
        step_line(idx, total, repo_name, "ok", elapsed,
                  f"{repo_size} copied to {dest_org}" + ("; uses Git LFS" if uses_lfs else ""))
        return {'status': 'success', 'elapsed': elapsed}

    except Exception as e:
        # Clean up on failure for migrate mode (safely) -- only what this run cloned
        if created:
            _undo_own_clone(repo_temp_path, temp_dir, repo_name, was_empty_folder)

        elapsed = time.time() - start_time
        error_msg = f"✗ {repo_name} FAILED after {elapsed:.1f}s: {str(e)}"
        log_message(error_msg, error_log)
        step_line(idx, total, repo_name, "FAILED", elapsed, str(e).splitlines()[-1][:120] if str(e) else "")
        return {'status': 'failed', 'elapsed': elapsed, 'error': str(e)}


def prompt_clone_format():
    """Prompt until the user explicitly chooses a working or mirror clone."""
    from Basic._station import option, section
    section("How to copy each repository")
    option("1", "Working copies", "A regular clone: the files of the default branch, ready to work in.")
    option("2", "Mirrors", "An archival copy of every branch and tag, without working files.")
    while True:
        choice = prompt_input("  Choose [1 or 2]: ")
        if choice in ("1", "2"):
            return choice == "2"
        say("  Choose 1 or 2.", "warning")


def print_download_warnings() -> None:
    """Uniform download limitations, shown before any download-mode confirmation."""
    from Basic._station import bullet, section
    section("Before you download")
    for text in (
            "Each repository arrives in <folder>/<organization>/<repository>.",
            "A working copy has the default branch's files; other branches stay on GitHub until you "
            "check them out. A mirror keeps every branch and tag, without working files.",
            "Repositories already here are skipped; a rerun skips the ones already finished.",
            "Private repositories appear only if your GitHub account can see them.",
            "Repositories that use Git LFS are marked; their large files need git lfs installed.",
            "Sizes are what GitHub reports; disk use can differ.",
            "A failed repository is logged and the rest continue; details are in the runs folder.",
            "Nothing is pushed, created, changed or deleted on GitHub."):
        bullet(text)