"""
batch
=====

Download orchestration for the org duplicator's granular modes:

  Mode 4: batch-download several namespaces (your account + your orgs) at once.
  Mode 5: download one single repo by `owner/name` or full URL (any public repo works).

Both share the uniform flow — namespace(s) -> target parent -> options -> inventory ->
optional repo-level pick (same selection grammar as namespaces: print-style ranges,
names, 'all', 'except'/'!') -> warnings -> one typed YES -> per-repo workers with
per-namespace resume files -> summary/manifest — and the same arrival layout:

    <parent>/<namespace>/<repo>

Import flows from Special._org_duplicator.batch. Remote checks/probes, per-repo workers and
resume state live in remote, operations and tracking, using shared Basic primitives.
This module does not execute a flow on import.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from Basic._confirm import (
    parse_selection,
    prompt_for_directory,
    prompt_input,
    prompt_yes_no,
    resolve_directory,
)
from Basic._console import PRINT_LOCK, format_size
from Basic._station import clean, line, menu_header, notice, row, run_header, say, section, summary
from Basic._providers.github import (
    check_repo_for_lfs,
    list_my_orgs,
    org_access_error,
    resolve_repo_details,
)
from Special._org_duplicator.local_repos import scan_local_git_repos
from Special._org_duplicator.operations import (
    download_single_repo,
    print_download_warnings,
    prompt_clone_format,
)
from Special._org_duplicator.remote import org_repos_with_details_safe
from Special._org_duplicator.tracking import (
    RUNS_DIR,
    initialize_tracking_files,
    load_completed_repos,
)


def choose_orgs(orgs):
    """Show memberships and return the user-selected subset. Re-prompts on bad input.

    Accepts print-style numbers and ranges (1-5, 7, 9-25), login names, 'all',
    and exclusions via 'except' or '!'.
    Examples: '1-5, 7, 9-25' · 'all except example-org' · 'all except 1,4' · 'all,!2-4'
    """
    section(f"Your account and organizations ({len(orgs)})")
    say(f"  {'#':>4}  {'Name':<30} {'Role':<8} State", "muted")
    for idx, org in enumerate(orgs, 1):
        state = org.get('state', '?') + ("  (you)" if org.get('personal') else "")
        say(f"  {idx:>4}  {clean(org['login']):<30} {org.get('role', '?'):<8} {state}")
    say()
    line("Choose by number or name: 1-5, 7 or all; except (or !) leaves some out, as in all except 2.",
         "muted")
    while True:
        raw = prompt_input("  Which to download: ")
        selected, bad = parse_selection(raw, orgs, key=lambda o: o['login'].lower())
        if bad:
            say(f"  Not recognized: {', '.join(bad)}. Try again.", "warning")
            continue
        if not selected:
            say("  That leaves nothing selected. Try again.", "warning")
            continue
        return selected


def _prompt_parallel():
    """Ask how many parallel downloads to run per org (1-5). Empty / bad input -> 3."""
    raw = prompt_input("  Downloads at once, 1 to 5 [3]: ")
    if raw.isdigit() and 1 <= int(raw) <= 5:
        return int(raw)
    return 3


def ask_filters(args=None, assume_yes=False):
    """Resolve the batch filters/options: a flag value wins, then (with --yes) a default,
    otherwise the interactive prompt. Applies to every org in the batch."""
    def resolved(attr, default, prompter):
        value = getattr(args, attr, None)
        if value is not None:
            return value
        return default if assume_yes else prompter()

    section("Which repositories")
    include_private = resolved(
        "private", True, lambda: prompt_yes_no("Include private repos?", default=True))
    include_archived = resolved(
        "archived", False, lambda: prompt_yes_no("Include archived repos?", default=False))
    include_forks = resolved(
        "forks", False, lambda: prompt_yes_no("Include forks?", default=False))

    clone_format = getattr(args, "format", None)
    if clone_format is not None:
        use_mirror = clone_format == "mirror"
    elif assume_yes:
        use_mirror = False
    else:
        use_mirror = prompt_clone_format()

    parallel_workers = getattr(args, "parallel", None)
    if parallel_workers is None:
        parallel_workers = 3 if assume_yes else _prompt_parallel()
    return include_private, include_archived, include_forks, use_mirror, parallel_workers


def filter_repos(repos, include_private, include_archived, include_forks):
    """Visibility/state filters chosen by the user at run time."""
    return [
        r for r in repos
        if (include_private or not r.get('isPrivate'))
        and (include_archived or not r.get('isArchived'))
        and (include_forks or not r.get('isFork'))
    ]


def pending_repos(repos, existing_names, completed_names):
    """Repos not already local/completed; GitHub names compare case-insensitively."""
    skip = {name.lower() for name in existing_names} | {name.lower() for name in completed_names}
    return [repo for repo in repos if repo['name'].lower() not in skip]

def download_one_org(item, root, use_mirror, parallel_workers):
    """Download one org's filtered repos into <root>/<org>. Returns a stats dict."""
    org = item['org']
    org_dir = os.path.join(root, org)
    section(f"{org}: {len(item['repos'])} repositories into {org_dir}")
    stats = {'org': org, 'planned': len(item['repos']), 'downloaded': 0,
             'skipped_existing': 0, 'failed': 0, 'error': None}
    try:
        os.makedirs(org_dir, exist_ok=True)
    except OSError as exc:
        line(f"Could not create the folder: {exc}", "error")
        stats['error'] = str(exc)
        return stats

    files = initialize_tracking_files('download', org, None, org_dir, scope=org)
    completed = load_completed_repos(files['completed'])
    existing_names = {r['name'] for r in item.get('existing', [])}
    remaining = pending_repos(item['repos'], existing_names, completed)
    stats['skipped_existing'] = len(item['repos']) - len(remaining)
    if stats['skipped_existing']:
        line(f"Skipping {stats['skipped_existing']} already here or finished in an earlier run.", "detail")
    if not remaining:
        line("Nothing to download.", "detail")
        return stats

    total = len(remaining)
    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = [
            executor.submit(
                download_single_repo,
                repo, idx, total, org, org_dir, use_mirror,
                files['completed'], files['success'], files['error']
            )
            for idx, repo in enumerate(remaining, 1)
        ]
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:  # a worker should never raise, but one bug must not abort the batch
                stats['failed'] += 1
                with PRINT_LOCK:
                    line(f"A download stopped unexpectedly: {exc}", "error")
                continue
            if result['status'] == 'success':
                stats['downloaded'] += 1
            else:
                stats['failed'] += 1
    line(f"{stats['downloaded']} downloaded, {stats['failed']} failed"
         + (f"; details in {files['error']}" if stats['failed'] else ""),
         "error" if stats['failed'] else "detail")
    stats['errors_file'] = str(files['error'])
    return stats

def _select_namespaces(orgs, spec):
    """Resolve --namespaces against the org list, or fall back to the interactive chooser."""
    if spec is None:
        return choose_orgs(orgs)
    selected, bad = parse_selection(spec, orgs, key=lambda o: o['login'].lower())
    if bad:
        notice("Nothing downloaded", f"--namespaces: not recognized: {', '.join(bad)}", "error")
        return []
    if not selected:
        notice("Nothing downloaded", "--namespaces leaves nothing selected.", "error")
        return []
    row("Namespaces", ", ".join(o['login'] for o in selected))
    return selected


def run_batch_download(args=None):
    assume_yes = bool(getattr(args, "yes", False))
    menu_header("Download your organizations")
    notice("Your account and organizations to this computer", "Choose which; it lists what it found "
           "and asks before it downloads anything.")
    say()
    line("Reading your organizations from GitHub...", "detail")
    orgs = list_my_orgs()
    if not orgs:
        notice("Nothing to download", "Your GitHub account belongs to no organizations.", "warning")
        return
    selected = _select_namespaces(orgs, getattr(args, "namespaces", None))
    if not selected:
        return

    dest = getattr(args, "dest", None)
    if dest is None:
        root = prompt_for_directory(
            "Parent directory (one <org> subfolder will be created per org): ",
            must_exist=False, create_ok=True,
        )
    else:
        root, error = resolve_directory(dest, create_missing=True)
        if error:
            notice("Nothing downloaded", f"--dest: {error}", "error")
            return
        row("Folder", str(root))

    (include_private, include_archived,
     include_forks, use_mirror, parallel_workers) = ask_filters(args, assume_yes)
    print_download_warnings()

    # ---- Inventory pass (read-only): access + repos + user filters + existing locals ----
    inventory = []
    section("What each has")
    for org in selected:
        login = org['login']
        error = org_access_error(login)
        if error:
            row(login, f"no access: {error}", "error")
            inventory.append({'org': login, 'repos': [], 'error': error})
            continue
        repos, fetch_error = org_repos_with_details_safe(login)
        if fetch_error:
            row(login, f"could not be listed: {fetch_error}", "error")
            inventory.append({'org': login, 'repos': [], 'error': fetch_error})
            continue
        kept = filter_repos(repos, include_private, include_archived, include_forks)
        excluded = len(repos) - len(kept)
        existing = scan_local_git_repos(os.path.join(root, login))
        note = f", {excluded} left out by your choices" if excluded else ""
        row(login, f"{len(repos)} repositories{note}, {len(existing)} already here", "success")
        inventory.append({'org': login, 'repos': kept, 'existing': existing, 'error': None})

    # ---- Repo-level granularity: the same grammar, per namespace (ENTER = all) ----
    if not assume_yes and prompt_yes_no("Pick individual repos per namespace?", default=False):
        for item in inventory:
            if item['error'] or not item['repos']:
                continue
            login = item['org']
            section(f"{login}: {len(item['repos'])} repositories")
            ordered = sorted(item['repos'], key=lambda r: r['name'].lower())
            for idx, repo in enumerate(ordered, 1):
                flags = "".join(flag for flag, on in (
                    (" private", repo.get('isPrivate')),
                    (" archived", repo.get('isArchived')),
                    (" fork", repo.get('isFork')),
                    (" LFS", repo.get('uses_lfs')),
                ) if on)
                say(f"  {idx:>4}  {clean(repo['name'])[:30]:<30} {format_size(repo.get('diskUsage', 0)):>9}{flags}")
            while True:
                raw = prompt_input(f"  Which of {login} (Enter for all; 1-5, names, except): ")
                selected, bad = parse_selection(raw, ordered, key=lambda r: r['name'].lower())
                if bad:
                    say(f"  Not recognized: {', '.join(bad)}. Try again.", "warning")
                    continue
                line(f"{login}: nothing selected; it is skipped." if not selected else
                     f"{login}: {len(selected)} of {len(ordered)} selected.", "detail")
                item['repos'] = selected
                break

    # ---- Confirmation: one table, one YES ----
    section("Plan")
    total_repos = total_kb = 0
    for item in inventory:
        if item['error']:
            row(item['org'], "unavailable; skipped", "error")
            continue
        size = sum(r.get('diskUsage', 0) for r in item['repos'])
        total_repos += len(item['repos'])
        total_kb += size
        row(item['org'], f"{len(item['repos'])} repositories, {format_size(size)}")
    row("Total", f"{total_repos} repositories, {format_size(total_kb)}, into {root}")
    if total_repos == 0:
        notice("Nothing to download", "Check your choices above. Nothing was changed.", "warning")
        return
    say()
    if not assume_yes and prompt_input("  Type YES to start, anything else cancels: ") != "YES":
        notice("Cancelled", "Nothing was downloaded.", "warning")
        return
    run_header("Downloading", f"{total_repos} repositories from {len(inventory)} namespaces",
               f"into {root}")

    # ---- Download pass ----
    started = datetime.now()
    results = []
    for item in inventory:
        if item['error'] or not item['repos']:
            results.append({'org': item['org'], 'planned': 0, 'downloaded': 0,
                            'skipped_existing': 0, 'failed': 0, 'error': item['error']})
            continue
        results.append(download_one_org(item, root, use_mirror, parallel_workers))
    show_summary(results, started, root, include_private, include_archived,
                 include_forks, use_mirror, parallel_workers)


def show_summary(results, started, root, include_private, include_archived,
                 include_forks, use_mirror, parallel_workers):
    """The run's Summary and one result notice; the manifest records the whole batch."""
    manifest = {
        'started': started.isoformat(timespec='seconds'),
        'finished': datetime.now().isoformat(timespec='seconds'),
        'root': root,
        'filters': {'private': include_private, 'archived': include_archived,
                    'forks': include_forks},
        'mirror': use_mirror,
        'parallel_workers': parallel_workers,
        'orgs': [{key: value for key, value in s.items() if key != 'errors_file'} for s in results],
        'totals': {
            'downloaded': sum(s['downloaded'] for s in results),
            'skipped_existing': sum(s['skipped_existing'] for s in results),
            'failed': sum(s['failed'] for s in results),
        },
    }
    facts = [f"{s['org']}: {s['downloaded']} of {s['planned']} downloaded"
             + (f", {s['skipped_existing']} already here" if s['skipped_existing'] else "")
             + (f", {s['failed']} failed" if s['failed'] else "")
             + (f" (unavailable: {s['error']})" if s['error'] else "") for s in results]
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = RUNS_DIR / f"batch_{started.strftime('%Y%m%d_%H%M%S')}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        facts.append(f"Record of this batch: {manifest_path}")
    except OSError as exc:
        facts.append(f"The batch record could not be written: {exc}")
    summary(facts)
    failed = manifest['totals']['failed']
    if failed:
        notice("Finished with failures", f"{failed} did not download. Run the same batch again to retry "
               "them; finished and existing repositories are skipped.", "error")
    else:
        notice("Finished", "Run the same batch again any time; it downloads only what is new.", "success")


def _spec_has_owner(spec):
    """True when the spec names an owner: 'owner/name', or a URL that carries one."""
    spec = spec.strip()
    return "/" in spec or "://" in spec


def _resolve_one_repo(spec):
    """Resolve a repo spec to gh's detail dict. Returns (data, problem_message).

    A bare token with no owner is reported specially: `gh repo view` silently prepends the
    authenticated user as the owner, which is almost never what someone typing a friend's
    name intends.
    """
    spec = spec.strip()
    if not spec:
        return None, "no repo given."
    if spec.startswith("-"):
        return None, f"'{spec}' starts with '-' — that is not a repo. Use owner/name or a URL."
    try:
        return resolve_repo_details(spec), None
    except (RuntimeError, json.JSONDecodeError) as exc:
        if not _spec_has_owner(spec):
            return None, (
                f"'{spec}' has no owner. GitHub reads a bare name as one of YOUR repos "
                f"('{spec}' -> a repo in your account), which is why it failed.\n"
                f"    Give owner/name (e.g. {spec}/their-repo) or a full URL."
            )
        return None, f"could not resolve '{spec}': {exc}"


def _resolve_repo_or_prompt(spec, allow_prompt):
    """Return the resolved repo dict, re-prompting on failure when allow_prompt. None = give up."""
    while True:
        if not spec:
            if not allow_prompt:
                notice("Nothing downloaded", "Name a repository: --single owner/name, or a URL.", "error")
                return None
            spec = prompt_input("  Repository (owner/name or a URL; Enter cancels): ").strip()
            if not spec:
                notice("Cancelled", "Nothing was downloaded.", "warning")
                return None
        had_owner = _spec_has_owner(spec)
        data, problem = _resolve_one_repo(spec)
        if data is not None:
            owner = (data.get('owner') or {}).get('login')
            name = data.get('name')
            if not owner or not name:
                line("GitHub returned no owner or name for that; try another.", "error")
                if not allow_prompt:
                    return None
                spec = None
                continue
            vis = "private" if data.get('isPrivate') else "public"
            say()
            row("Repository", f"{owner}/{name}")
            row("Size", f"{vis}, {format_size(data.get('diskUsage') or 0)}")
            if data.get('description'):
                row("Description", str(data['description'])[:120])
            if not had_owner:
                line("The owner was assumed: you gave only a name.", "warning")
            if not had_owner and allow_prompt:
                keep = prompt_input(f'  Use {owner}/{name}? Y keeps it, anything else asks again: ')
                if keep.lower() != "y":
                    spec = None
                    continue
            return data
        line(problem, "error")
        if not allow_prompt:
            return None
        spec = None


def run_single_repo(spec, root, args=None):
    """Mode 5: download one repo (owner/name or URL) into <root>/<owner>/<repo>."""
    assume_yes = bool(getattr(args, "yes", False))
    clone_format = getattr(args, "format", None)
    menu_header("Download one repository")

    data = _resolve_repo_or_prompt(spec, allow_prompt=not assume_yes)
    if data is None:
        return
    owner = data['owner']['login']
    repo = {'name': data['name'],
            'isPrivate': data.get('isPrivate', False),
            'isFork': data.get('isFork', False),
            'isArchived': data.get('isArchived', False),
            'diskUsage': data.get('diskUsage') or 0,
            'description': data.get('description') or ''}
    if repo['isFork'] or repo['isArchived']:
        tags = " and ".join(t for t in ("a fork" if repo['isFork'] else "",
                                        "archived" if repo['isArchived'] else "") if t)
        row("Note", f"this repository is {tags}")

    if root is None:
        if assume_yes:
            notice("Nothing downloaded", "--yes with --single needs --dest.", "error")
            return
        root = prompt_for_directory(
            "Parent directory (an <owner>/<repo> subfolder will be created inside): ",
            must_exist=False, create_ok=True,
        )

    repo['uses_lfs'] = check_repo_for_lfs(owner, repo['name'])
    if repo['uses_lfs']:
        row("Git LFS", "used: its large files need git lfs installed", "warning")

    print_download_warnings()

    org_dir = os.path.join(root, owner)
    files = initialize_tracking_files('download', owner, None, org_dir, scope=owner)
    existing = {r['name'].lower() for r in scan_local_git_repos(org_dir)}
    completed = {name.lower() for name in load_completed_repos(files['completed'])}
    if repo['name'].lower() in existing or repo['name'].lower() in completed:
        notice("Already here", f"{owner}/{repo['name']} is already in {org_dir}. Nothing to do.", "success")
        return

    if clone_format is not None:
        use_mirror = clone_format == "mirror"
    elif assume_yes:
        use_mirror = False
    else:
        use_mirror = prompt_clone_format()
    say()
    if not assume_yes and prompt_input(f"  Type YES to download {owner}/{repo['name']} into {org_dir}: ") != "YES":
        notice("Cancelled", "Nothing was downloaded.", "warning")
        return
    run_header("Downloading", f"{owner}/{repo['name']}", f"into {org_dir}")
    try:
        os.makedirs(org_dir, exist_ok=True)
    except OSError as exc:
        notice("Nothing downloaded", f"The folder could not be created: {exc}", "error")
        return
    result = download_single_repo(repo, 1, 1, owner, org_dir, use_mirror,
                                  files['completed'], files['success'], files['error'])
    summary([f"Saved in {org_dir}" if result['status'] == 'success' else f"Details in {files['error']}"])
    if result['status'] == 'success':
        notice("Finished", f"{owner}/{repo['name']} is downloaded.", "success")
    else:
        notice("Did not download", "Nothing was kept. Run the tool again to retry.", "error")
