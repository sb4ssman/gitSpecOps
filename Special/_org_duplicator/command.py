#!/usr/bin/env python3
"""
GitHub Organization Repository Tool

Interactive, confirmation-driven copying of whole GitHub organizations:
  1. Remote -> Local   (download an org's repos to disk)
  2. Local  -> Remote  (upload local repos into an org)
  3. Remote -> Remote  (migrate one org into another)
  4. All my orgs -> Local (batch download to <root>/<org>/<repo>)
  5. One repo -> Local (any single repo by owner/name or URL)

This file is the orchestrator only. Shared primitives live in Basic; supporting modules
are imported from Special._org_duplicator:
  remote       prerequisite checks and provider-backed probes
  local_repos  on-disk repo discovery and safe cleanup
  tracking     resume state / run files
  operations   the per-repo download/upload/migrate workers

Requires: git, and gh CLI authenticated (gh auth login).
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._confirm import (  # noqa: E402
    parse_selection,
    prompt_for_directory,
    prompt_input,
    prompt_yes_no,
    use_scripted_answers,
)
from Basic._console import enable_unicode_output, format_size  # noqa: E402
from Basic._station import (  # noqa: E402
    choose, clean, line, menu_header, notice, option, row, run_header, say, section, summary)
from Basic._providers.github import compare_repos  # noqa: E402
from Special._org_duplicator.local_repos import (  # noqa: E402
    duplicate_repo_names,
    scan_local_git_repos,
)
from Special._org_duplicator.operations import (  # noqa: E402
    download_single_repo,
    print_download_warnings,
    process_migrate_repo,
    process_upload_repo,
    prompt_clone_format,
)
from Special._org_duplicator.remote import (  # noqa: E402
    check_gh_authenticated,
    check_gh_installed,
    check_git_installed,
    check_org_access,
    get_repos_with_details,
    remind_git_credentials,
)
from Special._org_duplicator.tracking import (  # noqa: E402
    RUNS_DIR,
    initialize_tracking_files,
    load_completed_repos,
)

#: Downloads write locally; upload and migrate create repositories and push to the host.
EFFECT = "remote"


def non_repo_entries(directory_path, repos):
    """Names of items in directory_path that are not among the detected git repos."""
    repo_dir_names = set()
    for repo in repos:
        repo_dir_names.add(os.path.basename(repo['path']))
    try:
        entries = os.listdir(directory_path)
    except OSError:
        return []
    return sorted(name for name in entries if name not in repo_dir_names)


def choose_repo_subset(repos):
    """Optional repo-level granularity for download mode. ENTER keeps all repos.

    Same selection grammar as the batch mode ('1-5, 7' style, names, 'except'/'!').
    """
    if not repos:
        return repos
    raw = prompt_input("Repos to include ('1-5, 7' style, names; ENTER = all): ")
    selected, bad = parse_selection(raw, repos, key=lambda r: r['name'].lower())
    if bad:
        line(f"Not recognized: {', '.join(bad)} — keeping all repos.")
        return repos
    if len(selected) != len(repos):
        line(f"{len(selected)} of {len(repos)} repos selected.")
    return selected


def display_repo_table(repos, org_name):
    """The repositories of one organization, as a station section: a table, then totals."""
    section(f"Repositories in {org_name}")
    if not repos:
        line("None found.", "warning")
        return

    # Sort by creation date (oldest first)
    sorted_repos = sorted(repos, key=lambda r: r['createdAt'])
    say(f"  {'#':>4}  {'Name':<30} {'Size':>9}  {'Private':<7}  {'LFS':<3}  {'Created':<10}", "muted")
    lfs_repos = []
    for idx, repo in enumerate(sorted_repos, 1):
        name = repo['name'] if len(repo['name']) <= 30 else repo['name'][:29] + "~"
        size = format_size(repo.get('diskUsage', 0))
        private = "yes" if repo['isPrivate'] else "no"
        lfs = "yes" if repo['uses_lfs'] else "no"
        say(f"  {idx:>4}  {clean(name):<30} {size:>9}  {private:<7}  {lfs:<3}  {repo['createdAt'][:10]:<10}",
            "warning" if repo['uses_lfs'] else "text")
        if repo['uses_lfs']:
            lfs_repos.append(repo['name'])
    say()
    row("Total", f"{len(sorted_repos)} repositories, "
                 f"{format_size(sum(r.get('diskUsage', 0) for r in sorted_repos))}")
    if lfs_repos:
        notice(f"{len(lfs_repos)} use Git LFS: {', '.join(lfs_repos)}",
               "Install Git LFS (git lfs install) for their large files. A mirror may not carry LFS "
               "files, and the new organization may need LFS set up.", "warning")


def check_prerequisites():
    """Verify git, gh, and gh auth before any operation, as rows. Exits on failure."""
    section("Requirements")
    check_git_installed()
    check_gh_installed()
    check_gh_authenticated()
    remind_git_credentials()


def setup_operation():
    """Handle mode selection and input collection."""
    menu_header("Duplicate an organization")
    notice("Copy GitHub repositories", "Download an organization, upload a folder of repositories to "
           "one, or copy one organization to another. It lists what it found and asks before it copies.")
    check_prerequisites()

    section("What to copy")
    option("1", "Organization to this computer", "Download its repositories.")
    option("2", "This computer to an organization", "Upload the repositories in a folder.")
    option("3", "Organization to organization", "Copy between two organizations, through this computer.")
    option("4", "All my organizations to this computer", "Download every organization you belong to.")
    option("5", "One repository to this computer", "owner/name or a URL.")
    option("0", "Exit without copying")
    mode_choice = choose("123450", "0")
    if mode_choice == "0":
        sys.exit(0)

    if mode_choice == "1":
        operation_mode = 'download'
    elif mode_choice == "2":
        operation_mode = 'upload'
    elif mode_choice == "3":
        operation_mode = 'migrate'
    elif mode_choice == "4":
        operation_mode = 'batch'
    elif mode_choice == "5":
        operation_mode = 'single'
    else:
        notice("Nothing selected", "Run the tool again and choose 1 to 5.", "warning")
        sys.exit(1)

    say()

    # Collect mode-specific inputs
    config = {'operation_mode': operation_mode}

    if operation_mode == 'download':
        config['source_org'] = prompt_input("Source organization name: ")
        config['dest_org'] = None

        say()
        line("Verifying organization access...", "detail")
        check_org_access(config['source_org'])
        line(f"Access confirmed for {config['source_org']}", "success")
        say()

        # Format selection
        config['use_mirror'] = prompt_clone_format()
        say()

        # Get target directory (created if missing; re-prompts on a bad path)
        config['temp_dir'] = prompt_for_directory(
            "Target directory path (repos will be saved here): ",
            must_exist=False,
            create_ok=True,
        )
        say()

    elif operation_mode == 'upload':
        source_dir = prompt_for_directory(
            "Source directory path (scan for git repos): ",
            must_exist=True,
            create_ok=False,
        )
        config['source_dir'] = source_dir
        config['temp_dir'] = source_dir  # Reuse for consistency
        config['dest_org'] = prompt_input("Destination organization name: ")
        config['source_org'] = None
        say()

        line("Local repository scan scope:")
        say("    1. Recursive (find nested repositories; recommended)")
        say("    2. Direct children only (original behavior)")
        scan_choice = prompt_input("Scope (1 or 2, default 1): ")
        config['recursive_scan'] = scan_choice != "2"
        if scan_choice not in ("", "1", "2"):
            line("Invalid input, using recursive scan.")
        say()

        line("Verifying organization access...", "detail")
        check_org_access(config['dest_org'])
        line(f"Read access confirmed for {config['dest_org']} (write access is verified when repos are created)", "success")
        say()

    elif operation_mode == 'migrate':
        config['source_org'] = prompt_input("Source organization name: ")
        config['dest_org'] = prompt_input("Destination organization name: ")
        say()

        line("Verifying organization access...", "detail")
        check_org_access(config['source_org'])
        line(f"Access confirmed for {config['source_org']}", "success")
        check_org_access(config['dest_org'])
        line(f"Read access confirmed for {config['dest_org']} (write access is verified when repos are created)", "success")
        say()

    elif operation_mode == 'single':
        # The repo spec and target directory are collected inside run_single_repo so the
        # spec is resolved (and shown) before anything else is asked.
        config['source_spec'] = None
        config['source_org'] = None
        config['dest_org'] = None
        config['temp_dir'] = None

    return config


def validate_operation(config):
    """Check org access, detect repos, and handle conflicts."""
    operation_mode = config['operation_mode']

    if operation_mode == 'download':
        line("Detecting repos...", "detail")
        source_repos = get_repos_with_details(config['source_org'])

        line("Scanning target directory for existing repos...", "detail")
        existing_local = scan_local_git_repos(config['temp_dir'])
        dest_repos = existing_local

        line(f"{len(source_repos)} repos found in {config['source_org']}", "success")
        line(f"{len(existing_local)} repos already exist locally", "success")
        say()

    elif operation_mode == 'upload':
        scope = "recursively" if config.get('recursive_scan', True) else "in direct children"
        line(f"Scanning directory for git repositories {scope}...", "detail")
        local_repos = scan_local_git_repos(
            config['source_dir'], recursive=config.get('recursive_scan', True)
        )
        source_repos = local_repos

        duplicate_names = duplicate_repo_names(source_repos)
        if duplicate_names:
            say()
            line("Multiple local repositories map to the same GitHub repository name:", "error")
            for name, paths in sorted(duplicate_names.items()):
                say(f"    {name}:")
                for path in paths:
                    say(f"      {path}")
            line("Choose a narrower scan root or direct-child scope, then rerun.")
            sys.exit(1)

        line("Detecting existing repos in destination org...", "detail")
        dest_repos = get_repos_with_details(config['dest_org'])

        line(f"{len(source_repos)} git repositories found locally", "success")
        line(f"{len(dest_repos)} repos found in {config['dest_org']}", "success")
        say()

    else:  # migrate
        line("Detecting repos in both orgs...", "detail")
        source_repos = get_repos_with_details(config['source_org'])
        dest_repos = get_repos_with_details(config['dest_org'])

        line(f"{len(source_repos)} repos found in {config['source_org']}", "success")
        line(f"{len(dest_repos)} repos found in {config['dest_org']}", "success")
        say()

    # Initialize tracking files
    files = initialize_tracking_files(operation_mode, config.get('source_org'), config.get('dest_org'), config.get('temp_dir'))

    # Handle conflicts
    source_names = {repo['name'].lower(): repo['name'] for repo in source_repos}
    dest_names = {repo['name'].lower(): repo['name'] for repo in dest_repos}
    conflicts = set(source_names.keys()) & set(dest_names.keys())

    if conflicts:
        if operation_mode == 'download':
            say()
            section("Some repositories already exist in the target folder.")
            line(f"{len(conflicts)} of {len(source_repos)} repos already exist in "
                 f"{config['temp_dir']}:", "warning")
            for name_lower in sorted(conflicts):
                say(f"      {source_names[name_lower]}")
            say()
            line("These will be SKIPPED — left untouched, never overwritten.")

            others = non_repo_entries(config['temp_dir'], existing_local)
            if others:
                line(f"The target folder also holds {len(others)} other item(s), e.g.:", "warning")
                for name in others[:10]:
                    say(f"      {name}")
            say()

            for name_lower in conflicts:
                repo_name = source_names[name_lower]
                if repo_name not in load_completed_repos(files['completed']):
                    with open(files['completed'], 'a', encoding='utf-8') as f:
                        f.write(f"{repo_name}\n")

            if not prompt_yes_no("Continue with download?", default=False):
                line("Aborted by user.")
                sys.exit(0)
            say()

        elif operation_mode == 'upload':
            say()
            section("Matching repository names found in destination org.")
            line(f"{len(conflicts)} repos already exist remotely and will be skipped", "success")

            for name_lower in conflicts:
                repo_name = source_names[name_lower]
                if repo_name not in load_completed_repos(files['completed']):
                    with open(files['completed'], 'a', encoding='utf-8') as f:
                        f.write(f"{repo_name}\n")
            say()

        else:  # migrate
            say()
            section("Matching repository names found. Verifying if duplicates...")

            actual_conflicts = []
            verified_duplicates = []

            for name_lower in sorted(conflicts):
                repo_name = source_names[name_lower]
                say(f"  Checking: {repo_name}...", end=' ')

                is_identical, reason = compare_repos(config['source_org'], config['dest_org'], repo_name)

                if is_identical:
                    line("Verified duplicate", "success")
                    verified_duplicates.append(repo_name)
                else:
                    line(f"Different ({reason})", "error")
                    actual_conflicts.append(repo_name)

            say()

            if actual_conflicts:
                line("Non-duplicate repositories with matching names found:", "error")
                for name in actual_conflicts:
                    say(f"    - {name}")
                say()
                line("This tool is intended ONLY to copy one whole github org")
                line("into one raw empty org, and it is not built to deal with conflicts.")
                sys.exit(1)

            if verified_duplicates:
                line(f"All {len(verified_duplicates)} matching repos are verified duplicates", "success")
                line("These will be skipped during migration.")
                for repo_name in verified_duplicates:
                    if repo_name not in load_completed_repos(files['completed']):
                        with open(files['completed'], 'a', encoding='utf-8') as f:
                            f.write(f"{repo_name}\n")
                say()
    else:
        line("No conflicts!", "success")
        say()

    return source_repos, dest_repos, files


def show_summary(operation_mode, total_repos, successful, failed, temp_dir, files):
    """The run's Summary and one result notice."""
    where = {"download": f"saved in {temp_dir}", "upload": f"uploaded from {temp_dir}",
             "migrate": "copied between the organizations"}.get(operation_mode, "")
    summary([f"{successful} of {total_repos} repositories {where}",
             f"{failed} failed; details in {files['error']}" if failed else "",
             f"Finished repositories are listed in {files['completed']}; a rerun skips them"])
    if failed:
        notice("Finished with failures", f"{failed} did not copy. Run the tool again to retry them; "
               "the rest are kept.", "error")
    else:
        notice("Finished", "Every repository copied.", "success")


_EPILOG = f"""\
Modes (interactive menu when run with no flags):
  1. Remote -> Local download
  2. Local -> Remote upload
  3. Remote -> Remote migration
  4. All my orgs -> Local batch download
  5. One repo -> Local (owner/name or URL)

Non-interactive (so it runs cleanly inside editors/CI where a terminal helper may
inject keystrokes into an open prompt):

  # Back up every namespace, working clones, no further questions:
  github_org_duplicator.py --batch --namespaces all --dest /backups/github --yes

  # Batch, skip one org, mirror clones:
  github_org_duplicator.py --batch --namespaces 'all,!some-org' \\
      --dest /backups/github --format mirror --yes

  # One repo:
  github_org_duplicator.py --single owner/name --dest /backups/github --yes

  # Any mode, answers pre-supplied one per line (blank line = that prompt's default):
  github_org_duplicator.py --answers answers.txt

--yes takes documented defaults for any batch option not given as a flag
(private: yes, archived: no, forks: no, format: working, parallel: 3) and skips the
final typed confirmation. It requires --namespaces and --dest.

Run files: {RUNS_DIR}
"""


def _enter_batch(args):
    """True when any flag signals batch mode (--single is handled before this is called)."""
    return args.batch or any(
        getattr(args, name) is not None
        for name in ("namespaces", "dest", "private", "archived", "forks", "parallel")
    )


def parse_args(argv=None):
    """Parse CLI flags. No flags -> fully interactive (the historical behavior)."""
    parser = argparse.ArgumentParser(
        prog="duplicate_org.py",
        description="Cautious copying of whole GitHub namespaces (see modes below).",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--batch", action="store_true",
                        help="Run mode 4 (batch download) without the menu.")
    parser.add_argument("--single", metavar="OWNER/NAME|URL",
                        help="Run mode 5 (one repo) without the menu.")
    parser.add_argument("--namespaces", metavar="SPEC",
                        help="Batch: which namespaces — 'all', '1-5,7', names, 'all,!org'.")
    parser.add_argument("--dest", metavar="DIR",
                        help="Batch/single: parent directory (created if missing).")
    parser.add_argument("--private", action=argparse.BooleanOptionalAction, default=None,
                        help="Batch: include private repos (default: yes).")
    parser.add_argument("--archived", action=argparse.BooleanOptionalAction, default=None,
                        help="Batch: include archived repos (default: no).")
    parser.add_argument("--forks", action=argparse.BooleanOptionalAction, default=None,
                        help="Batch: include forks (default: no).")
    parser.add_argument("--format", choices=("working", "mirror"), default=None,
                        help="Clone format for batch/single (default: working).")
    parser.add_argument("--parallel", type=int, metavar="N", default=None,
                        help="Batch: parallel downloads per namespace, 1-5 (default: 3).")
    parser.add_argument("--yes", action="store_true",
                        help="Assume YES and take defaults for unspecified batch options.")
    parser.add_argument("--answers", metavar="FILE", type=Path,
                        help="Feed answers to any remaining prompt, one per line.")
    args = parser.parse_args(argv)

    if args.batch and args.single:
        parser.error("--batch and --single are mutually exclusive")
    if args.parallel is not None and not 1 <= args.parallel <= 5:
        parser.error("--parallel must be between 1 and 5")
    if args.yes and not (args.single or _enter_batch(args)):
        parser.error("--yes only applies to --batch or --single")
    if args.yes and args.batch and (not args.namespaces or not args.dest):
        parser.error("--yes with --batch requires --namespaces and --dest")
    if args.yes and args.single and not args.dest:
        parser.error("--yes with --single requires --dest")
    return args


def main(argv=None):
    """Run the existing duplicator with explicit argv or the direct script's arguments."""
    # ✓/✗/⚠/→ are not cp1252-encodable; widen the streams before a redirected run prints.
    enable_unicode_output()
    args = parse_args(argv)

    if args.answers is not None:
        try:
            lines = args.answers.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError) as exc:
            line(f"cannot read --answers file {args.answers}: {exc}", "error")
            sys.exit(2)
        if lines and lines[-1] == "":
            lines.pop()  # drop the phantom entry from a trailing newline
        use_scripted_answers(lines, strict=bool(args.yes))

    # --- Non-interactive entry points ---
    if args.single is not None:
        check_prerequisites()
        from Special._org_duplicator.batch import run_single_repo
        run_single_repo(args.single, args.dest, args)
        return

    if _enter_batch(args):
        check_prerequisites()
        from Special._org_duplicator.batch import run_batch_download
        run_batch_download(args)
        return

    # --- Interactive menu (unchanged) ---
    config = setup_operation()
    operation_mode = config['operation_mode']

    if operation_mode == 'batch':
        from Special._org_duplicator.batch import run_batch_download
        run_batch_download()
        return

    if operation_mode == 'single':
        from Special._org_duplicator.batch import run_single_repo
        run_single_repo(None, None)
        return

    # Validate operation (check access, detect repos, handle conflicts)
    source_repos, dest_repos, files = validate_operation(config)

    # Display repository information
    if operation_mode == 'download':
        display_repo_table(source_repos, config['source_org'])
        print_download_warnings()
        source_repos = choose_repo_subset(source_repos)
    elif operation_mode == 'upload':
        section("Repositories found on this computer")
        if not source_repos:
            line("None found.", "warning")
        else:
            say(f"  {'#':>4}  {'Name':<40} {'Kind':<8}", "muted")
            for idx, repo in enumerate(sorted(source_repos, key=lambda r: r['name']), 1):
                kind = "mirror" if repo.get('is_mirror', False) else "working"
                say(f"  {idx:>4}  {clean(repo['name'])[:40]:<40} {kind:<8}")
            say()
            row("Total", f"{len(source_repos)} repositories")
    else:  # migrate
        display_repo_table(source_repos, config['source_org'])
        display_repo_table(dest_repos, config['dest_org'])

    # Pause for user review
    notice("Review the repositories above", "Nothing has been copied. Next: where and how.")
    prompt_input("  Press Enter to continue: ")

    # Get temp directory for migrate mode
    if operation_mode == 'migrate':
        config['temp_dir'] = prompt_for_directory(
            "Temporary directory path (for cloning): ",
            must_exist=False,
            create_ok=True,
        )
        say()

    # Load completed repos
    completed_repos = load_completed_repos(files['completed'])
    remaining_repos = [r for r in source_repos if r['name'] not in completed_repos]

    section("Ready")
    if completed_repos:
        row("Already finished", f"{len(completed_repos)} repositories (skipped)")
    verb = {"download": f"download from {config['source_org']}", "upload": f"upload to {config['dest_org']}",
            "migrate": f"copy from {config['source_org']} to {config['dest_org']}"}[operation_mode]
    row("To do", f"{len(remaining_repos)} repositories: {verb}")
    if config.get('temp_dir'):
        row("Folder", str(config['temp_dir']))

    # Ask about parallel operations for download mode
    parallel_workers = 1
    if operation_mode == 'download' and len(remaining_repos) > 1:
        parallel_input = prompt_input("  Downloads at once, 1 to 5 [3]: ")
        if parallel_input.isdigit() and 1 <= int(parallel_input) <= 5:
            parallel_workers = int(parallel_input)
        else:
            parallel_workers = 3
        row("At once", f"{parallel_workers} downloads")

    # Confirm before proceeding
    say()
    confirmation = prompt_input('  Type YES to start, anything else cancels: ')
    if confirmation != "YES":
        notice("Cancelled", "Nothing was copied.", "warning")
        sys.exit(0)

    run_header({"download": "Downloading", "upload": "Uploading", "migrate": "Copying"}[operation_mode],
               f"{len(remaining_repos)} repositories: {verb}",
               f"folder: {config.get('temp_dir') or '-'}  |  log: {files['success']}")

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
                    repo, config['dest_org'], files['completed'], files['success'], files['error'],
                    idx, total_repos
                )
            else:  # migrate
                result = process_migrate_repo(
                    repo, config['source_org'], config['dest_org'], config['temp_dir'],
                    files['completed'], files['success'], files['error'], idx, total_repos
                )
            if result['status'] == 'success':
                successful += 1
            else:
                failed += 1

    # Show summary
    show_summary(operation_mode, total_repos, successful, failed, config['temp_dir'], files)


def cli_main(argv=None):
    """Run the command with its existing interrupt/resume handling."""
    try:
        return main(argv)
    except KeyboardInterrupt:
        say()
        notice("Stopped", "Some repositories may have finished; they are recorded, and running the "
               "tool again continues with the rest.", "warning")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
