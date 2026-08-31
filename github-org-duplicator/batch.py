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

Flow only: gh calls live in gh_remote, per-repo work in operations, resume state in
tracking.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from gh_common import (
    RUNS_DIR,
    format_size,
    parse_selection,
    prompt_clone_format,
    print_download_warnings,
    prompt_for_directory,
    prompt_input,
    prompt_yes_no,
)
from gh_remote import (
    check_repo_for_lfs,
    list_my_orgs,
    org_access_error,
    org_repos_with_details_safe,
    resolve_repo_details,
)
from local_repos import scan_local_git_repos
from operations import download_single_repo
from tracking import initialize_tracking_files, load_completed_repos


def choose_orgs(orgs):
    """Show memberships and return the user-selected subset. Re-prompts on bad input.

    Accepts print-style numbers and ranges (1-5, 7, 9-25), login names, 'all',
    and exclusions via 'except' or '!'.
    Examples: '1-5, 7, 9-25' · 'all except example-org' · 'all except 1,4' · 'all,!2-4'
    """
    print()
    print(f"Orgs the authenticated account belongs to: {len(orgs)}")
    print(f"{'#':<4} {'Login':<30} {'Role':<8} State")
    print("-" * 60)
    for idx, org in enumerate(orgs, 1):
        state = org.get('state', '?')
        if org.get('personal'):
            state += "  (you)"
        print(f"{idx:<4} {org['login']:<30} {org.get('role', '?'):<8} {state}")
    print()
    while True:
        raw = prompt_input(
            "Namespaces to download ('1-5, 7, 9-25' style, names, 'all'; "
            "'except' or '!' excludes): "
        )
        selected, bad = parse_selection(raw, orgs, key=lambda o: o['login'].lower())
        if bad:
            print(f"Not recognized: {', '.join(bad)}. Try again.")
            continue
        if not selected:
            print("Selection is empty after exclusions. Try again.")
            continue
        return selected


def ask_filters():
    """Prompt once for the filters and options applied to every org in the batch."""
    print()
    include_private = prompt_yes_no("Include private repos?", default=True)
    include_archived = prompt_yes_no("Include archived repos?", default=False)
    include_forks = prompt_yes_no("Include forks?", default=False)
    print()
    use_mirror = prompt_clone_format()
    print()
    parallel_workers = 3
    parallel_input = prompt_input("Number of parallel downloads per org (1-5, default 3): ")
    if not parallel_input:
        pass
    elif parallel_input.isdigit() and 1 <= int(parallel_input) <= 5:
        parallel_workers = int(parallel_input)
    else:
        print("Invalid input, using default (3)")
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
    print()
    print("=" * 60)
    print(f"[{org}] downloading {len(item['repos'])} repos -> {org_dir}")
    print("=" * 60)
    stats = {'org': org, 'planned': len(item['repos']), 'downloaded': 0,
             'skipped_existing': 0, 'failed': 0, 'error': None}
    try:
        os.makedirs(org_dir, exist_ok=True)
    except OSError as exc:
        print(f"  ✗ [{org}] Could not create folder: {exc}")
        stats['error'] = str(exc)
        return stats

    files = initialize_tracking_files('download', org, None, org_dir, scope=org)
    completed = load_completed_repos(files['completed'])
    existing_names = {r['name'] for r in item.get('existing', [])}
    remaining = pending_repos(item['repos'], existing_names, completed)
    stats['skipped_existing'] = len(item['repos']) - len(remaining)
    if stats['skipped_existing']:
        print(f"  [{org}] skipping {stats['skipped_existing']} repo(s) already local "
              f"or completed in a previous run")
    if not remaining:
        print(f"  [{org}] nothing to download.")
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
            result = future.result()
            if result['status'] == 'success':
                stats['downloaded'] += 1
            else:
                stats['failed'] += 1
    print(f"  [{org}] done: {stats['downloaded']} downloaded, {stats['failed']} failed "
          f"(errors: {files['error']})")
    return stats

def run_batch_download():
    print()
    print("=" * 60)
    print("Batch download: all my orgs -> Local")
    print("=" * 60)

    print("Listing your org memberships...")
    orgs = list_my_orgs()
    if not orgs:
        print("No org memberships found for the authenticated account. Nothing to do.")
        return
    selected = choose_orgs(orgs)
    root = prompt_for_directory(
        "Parent directory (one <org> subfolder will be created per org): ",
        must_exist=False, create_ok=True,
    )
    (include_private, include_archived,
     include_forks, use_mirror, parallel_workers) = ask_filters()
    print_download_warnings()

    # ---- Inventory pass (read-only): access + repos + user filters + existing locals ----
    inventory = []
    for org in selected:
        login = org['login']
        print()
        print(f"--- {login}: checking access and inventory...")
        error = org_access_error(login)
        if error:
            print(f"  ✗ No access: {error}")
            inventory.append({'org': login, 'repos': [], 'error': error})
            continue
        repos, fetch_error = org_repos_with_details_safe(login)
        if fetch_error:
            print(f"  ✗ Fetch failed: {fetch_error}")
            inventory.append({'org': login, 'repos': [], 'error': fetch_error})
            continue
        kept = filter_repos(repos, include_private, include_archived, include_forks)
        excluded = len(repos) - len(kept)
        existing = scan_local_git_repos(os.path.join(root, login))
        note = f", {excluded} excluded by filters" if excluded else ""
        print(f"  ✓ {len(repos)} repos{note}, {len(existing)} already local")
        inventory.append({'org': login, 'repos': kept, 'existing': existing, 'error': None})

    # ---- Repo-level granularity: the same grammar, per namespace (ENTER = all) ----
    if prompt_yes_no("Pick individual repos per namespace?", default=False):
        for item in inventory:
            if item['error'] or not item['repos']:
                continue
            login = item['org']
            print(f"\n[{login}] {len(item['repos'])} repos:")
            ordered = sorted(item['repos'], key=lambda r: r['name'].lower())
            for idx, repo in enumerate(ordered, 1):
                flags = "".join(flag for flag, on in (
                    (" private", repo.get('isPrivate')),
                    (" archived", repo.get('isArchived')),
                    (" fork", repo.get('isFork')),
                    (" LFS", repo.get('uses_lfs')),
                ) if on)
                print(f"{idx:>3}. {repo['name']:<40}{format_size(repo.get('diskUsage', 0)):>10}{flags}")
            while True:
                raw = prompt_input(f"Repos of {login} (ENTER = all; ranges/names/'except') : ")
                selected, bad = parse_selection(raw, ordered, key=lambda r: r['name'].lower())
                if bad:
                    print(f"Not recognized: {', '.join(bad)}. Try again.")
                    continue
                if not selected:
                    print(f"  {login}: nothing selected — namespace will be skipped.")
                else:
                    print(f"  {login}: {len(selected)} of {len(ordered)} repos selected.")
                item['repos'] = selected
                break

    # ---- Confirmation: one table, one YES ----
    print()
    print("=" * 80)
    print("Batch plan")
    print("=" * 80)
    total_repos = total_kb = 0
    for item in inventory:
        if item['error']:
            print(f"  {item['org']:<24} UNAVAILABLE: {item['error']}")
            continue
        size = sum(r.get('diskUsage', 0) for r in item['repos'])
        total_repos += len(item['repos'])
        total_kb += size
        print(f"  {item['org']:<24} {len(item['repos']):>4} repos  {format_size(size):>10}"
              f"  ->  {os.path.join(root, item['org'])}")
    print("-" * 80)
    print(f"  TOTAL: {total_repos} repos, {format_size(total_kb)}, "
          f"into {len(inventory)} org folder(s) under {root}")
    if total_repos == 0:
        print("Nothing to download (check your filter answers). No changes made.")
        return
    print()
    if prompt_input('Type "YES" to start the batch download: ') != "YES":
        print("Aborted. Nothing was downloaded.")
        return

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
    print()
    print("=" * 60)
    print("Batch complete")
    print("=" * 60)
    for s in results:
        note = f"  (error: {s['error']})" if s['error'] else ""
        print(f"  {s['org']:<24} downloaded {s['downloaded']}/{s['planned']}  "
              f"skipped {s['skipped_existing']}  failed {s['failed']}{note}")
    manifest = {
        'started': started.isoformat(timespec='seconds'),
        'finished': datetime.now().isoformat(timespec='seconds'),
        'root': root,
        'filters': {'private': include_private, 'archived': include_archived,
                    'forks': include_forks},
        'mirror': use_mirror,
        'parallel_workers': parallel_workers,
        'orgs': results,
        'totals': {
            'downloaded': sum(s['downloaded'] for s in results),
            'skipped_existing': sum(s['skipped_existing'] for s in results),
            'failed': sum(s['failed'] for s in results),
        },
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_DIR / f"batch_{started.strftime('%Y%m%d_%H%M%S')}.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    print(f"\nBatch manifest: {manifest_path}")
    print("Resume: rerun the same batch; completed and already-local repos are skipped.")


def run_single_repo(spec, root):
    """Mode 5: download one repo (owner/name or URL) into <root>/<owner>/<repo>."""
    print()
    print("=" * 60)
    print("Single repo -> Local")
    print("=" * 60)
    try:
        data = resolve_repo_details(spec)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"✗ Could not resolve '{spec}': {exc}")
        print("  Use owner/name or a full URL, e.g. https://github.com/owner/name")
        return
    owner = data['owner']['login']
    repo = {'name': data['name'],
            'isPrivate': data.get('isPrivate', False),
            'isFork': data.get('isFork', False),
            'isArchived': data.get('isArchived', False),
            'diskUsage': data.get('diskUsage', 0),
            'description': data.get('description') or ''}
    visibility = "private" if repo['isPrivate'] else "public"
    print(f"\n  {owner}/{repo['name']}  {format_size(repo['diskUsage'])}  {visibility}"
          f"{'  fork' if repo['isFork'] else ''}{'  ARCHIVED' if repo['isArchived'] else ''}")
    if repo['description']:
        print(f"  {repo['description'][:80]}")
    repo['uses_lfs'] = check_repo_for_lfs(owner, repo['name'])
    if repo['uses_lfs']:
        print("  ⚠ uses Git LFS")

    print_download_warnings()

    org_dir = os.path.join(root, owner)
    files = initialize_tracking_files('download', owner, None, org_dir, scope=owner)
    existing = {r['name'].lower() for r in scan_local_git_repos(org_dir)}
    completed = {name.lower() for name in load_completed_repos(files['completed'])}
    if repo['name'].lower() in existing or repo['name'].lower() in completed:
        print(f"\n✓ {owner}/{repo['name']} already exists locally or is logged complete. Nothing to do.")
        return

    print()
    use_mirror = prompt_clone_format()
    print()
    if prompt_input(f'Type "YES" to download {owner}/{repo["name"]} into {org_dir}: ') != "YES":
        print("Aborted. Nothing was downloaded.")
        return
    try:
        os.makedirs(org_dir, exist_ok=True)
    except OSError as exc:
        print(f"✗ Could not create folder: {exc}")
        return
    result = download_single_repo(repo, 1, 1, owner, org_dir, use_mirror,
                                  files['completed'], files['success'], files['error'])
    print()
    print(f"Done: {result['status']} — resume/manifest files in {files['completed'].parent}")
