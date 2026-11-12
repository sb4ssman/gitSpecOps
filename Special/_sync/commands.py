"""The command-line adapters behind Special's sync commands: one function per public command.

Why:          the public files in Special/ stay thin (a header, EFFECT and `main`); argument
              parsing and printing live here, the work itself in the sibling plumbing.
Reads:        see each command's own header.
May change:   see each command's own header and EFFECT.
Results:      printed text, or JSON where a command offers --json.
Layer:        Special: this machine, once.
Status:       working
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from Basic._console import enable_unicode_output
from Special._settings.fleet import fleet_directory, load_fleet_settings


def _profile(parser: argparse.ArgumentParser, roots: bool = True) -> None:
    parser.add_argument("--config-dir", type=Path, help="local fleet state and legacy input directory")
    parser.add_argument("--settings-home", type=Path, help="common profile; defaults to the user-data home")
    if roots:
        parser.add_argument("--root", action="append", type=Path,
                            help="observe this folder instead of the saved roots (repeatable)")


def _run(handler, parser, argv) -> int:
    enable_unicode_output()
    args = parser.parse_args(argv)
    try:
        return handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _locked(args):
    """The fleet's own lock: never act on the observed checkouts beside a running peer."""
    from Special._sync.lock import app_lock

    return app_lock(fleet_directory(args.config_dir, home=args.settings_home))


def _observer(args):
    from Special._sync.inventory import IncrementalObserver
    from Special._sync.selection import load_selection

    selection = load_selection(args.config_dir, home=args.settings_home, roots=args.root)
    return selection, IncrementalObserver(selection)


# --------------------------------------------------------------------------- suggest_sync

def _root_specs(args, config):
    from Special._sync.observer import RootSpec

    cli_roots = [RootSpec(Path(root), args.recursive) for root in (args.root or [])]
    cli_roots += [RootSpec(Path(root), True) for root in (args.recursive_root or [])]
    if cli_roots:
        return cli_roots, "command line"
    if config and config.get("roots"):
        return ([RootSpec(Path(root["path"]), bool(root.get("recursive")))
                 for root in config["roots"]], "saved configuration")
    return [], "nowhere"


def suggest_sync(args) -> int:
    from Special._security._advice import inspect_paths, render_advice
    from Special._sync.advice import render_table
    from Special._sync.config import load_branches, load_catalog, load_config, merge_catalog, save_catalog
    from Special._sync.manifest import build_manifest, fleet_id_for, new_fleet_secret
    from Special._sync.observer import observe_roots

    home = args.settings_home
    config_dir = fleet_directory(args.config_dir, home=home)
    config = load_config(config_dir, home=home)
    specs, source = _root_specs(args, config)
    snapshot = config.snapshot if hasattr(config, "snapshot") else load_fleet_settings(home)
    if snapshot is not None:
        snapshot.check_roots("sync", [spec.path for spec in specs])
    if not specs:
        raise ValueError("no roots to observe; pass --root, or save roots with "
                         "Elaborate/publish_status.py init")
    stream = sys.stderr if args.json else sys.stdout
    if args.fetch:
        print(f"Fetching remote refs for repositories in {len(specs)} root(s): the only network "
              "activity, and it never touches your working tree.", file=stream)
    # Repository ids only need a salt inside this run; nothing here leaves the machine.
    secret = (config or {}).get("fleet_secret") or new_fleet_secret()
    observation = observe_roots(specs, secret, fetch=args.fetch, fetch_workers=args.fetch_workers,
                                fetch_timeout=args.fetch_timeout)
    security = inspect_paths(zip((repo["repo_id"] for repo in observation.repositories),
                                 observation.locations),
                             settings_home=home, expected_settings=snapshot)
    machine = (config or {}).get("machine_id") or "this-machine"
    manifest = build_manifest(fleet_id_for(secret), machine,
                              (config or {}).get("machine_label") or machine, observation.repositories)
    merged = merge_catalog(load_catalog(config_dir), observation.catalog)
    branches = {**load_branches(config_dir), **observation.branches}
    if config and not args.no_catalog:
        save_catalog(config_dir, merged, branches)
    if args.json:
        print(json.dumps({"schema_version": 1, "manifest": manifest, "local_security": security,
                          "artifacts": []}, indent=2, sort_keys=True))
    else:
        print(render_table(manifest, merged, branches, security=security))
        print("\n" + render_advice(security))
    print(f"\nObserved {len(observation.repositories)} repositor(ies) from {source}. "
          "Nothing was published.", file=stream)
    for issue in observation.issues:
        print(f"warning: {issue}", file=sys.stderr)
    return 0


def suggest_sync_main(argv=None) -> int:
    from Special._sync.observer import DEFAULT_FETCH_TIMEOUT_SECONDS, DEFAULT_FETCH_WORKERS

    parser = argparse.ArgumentParser(prog="suggest_sync",
                                     description="Suggest what this machine's repositories need.")
    _profile(parser, roots=False)
    parser.add_argument("--root", action="append", help="root to inspect (overrides saved roots)")
    parser.add_argument("--recursive-root", action="append", help="recursive root (overrides saved)")
    parser.add_argument("--recursive", action="store_true", help="scan every --root recursively")
    parser.add_argument("--fetch", action="store_true",
                        help="refresh remote-tracking refs first so ahead/behind are current")
    parser.add_argument("--fetch-workers", type=int, default=DEFAULT_FETCH_WORKERS)
    parser.add_argument("--fetch-timeout", type=int, default=DEFAULT_FETCH_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true", help="machine-readable result")
    parser.add_argument("--no-catalog", action="store_true", help="do not update the local catalog")
    return _run(suggest_sync, parser, argv)


# --------------------------------------------------------------------------- name_repo

def name_repo(args) -> int:
    from Special._sync.config import load_catalog, save_catalog

    config_dir = fleet_directory(args.config_dir, home=args.settings_home)
    catalog = load_catalog(config_dir)
    if args.list or not args.repo_id:
        for repo_id, entry in sorted(catalog.items(), key=lambda item: item[0]):
            name = entry.get("alias") or entry.get("display_name") or "(unnamed)"
            marker = " (alias)" if entry.get("alias") else ""
            print(f"{repo_id[:12]}  {name}{marker}")
        if not catalog:
            print("Catalog is empty. Run suggest_sync first.")
        return 0
    if not args.name:
        raise ValueError("name_repo needs both a repo id and a name (or use --list)")
    matches = [repo_id for repo_id in catalog if repo_id.startswith(args.repo_id)]
    if len(matches) != 1:
        raise ValueError(f"{'no' if not matches else 'ambiguous'} repo id for {args.repo_id!r}")
    catalog[matches[0]] = {**catalog[matches[0]], "alias": args.name}
    save_catalog(config_dir, catalog)
    print(f"{matches[0][:12]} -> {args.name}")
    return 0


def name_repo_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="name_repo",
                                     description="Name a repository in the local-only catalog.")
    _profile(parser, roots=False)
    parser.add_argument("repo_id", nargs="?", help="repo id or unique prefix")
    parser.add_argument("name", nargs="?", help="readable name to show for it")
    parser.add_argument("--list", action="store_true", help="list catalog entries")
    return _run(name_repo, parser, argv)


# --------------------------------------------------------------------------- catch_up

def catch_up(args) -> int:
    from Special._sync.actions import apply_catchup, plan_catchup, render_catchup

    if args.apply and not args.yes:
        raise ValueError("--apply requires --yes after you review the plan")
    with _locked(args):
        return _catch_up(args)


def _catch_up(args) -> int:
    from Special._sync.actions import apply_catchup, plan_catchup, render_catchup

    _selection, observer = _observer(args)
    count = observer.inventory()
    print(f"Inventory found {count} observed repository(ies). Fetching their remotes without "
          "changing branches, indexes, or files.")
    plan = plan_catchup(observer.paths)
    print(render_catchup(plan))
    if not args.apply:
        return 0
    results = apply_catchup(plan)
    print("\n" + render_catchup(results, applied=True))
    return 1 if any(item["action"] in {"fetch_failed", "pull_failed", "pull_needs_review"}
                    for item in results) else 0


def catch_up_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="catch_up", description=(
        "Fetch every observed repository and preview safe fast-forwards; --apply --yes pulls "
        "only clean, behind-only checkouts."))
    _profile(parser)
    parser.add_argument("--apply", action="store_true", help="fast-forward the safe checkouts")
    parser.add_argument("--yes", action="store_true", help="confirm --apply after review")
    return _run(catch_up, parser, argv)


# --------------------------------------------------------------------------- audit_repos

def audit_repos(args) -> int:
    from Special._sync.actions import audit_repositories, every_repository, render_audit
    from Special._sync.selection import load_selection

    selection = load_selection(args.config_dir, home=args.settings_home, roots=args.root)
    # Its own walk, not the observer's inventory: that drops the repositories without an origin
    # which are exactly what an audit exists to find.
    hits, problems = every_repository(selection["roots"])
    rows = [{"path": row["path"], "name": row["name"], "origin": None,
             "findings": ["configured root missing"]} for row in problems]
    rows += [{"path": Path(hit.path), "name": Path(hit.path).name, "origin": None,
              "findings": ["bare repository (not audited)"]} for hit in hits if hit.kind == "bare"]
    rows += audit_repositories([hit.path for hit in hits if hit.kind != "bare"])
    if args.json:
        print(json.dumps([{**row, "path": str(row["path"])} for row in rows], indent=2))
    else:
        print(f"Found {len(hits)} repository(ies) under the configured roots.")
        print(render_audit(rows))
    return 1 if any(item["findings"] != ["no audited issue"] for item in rows) else 0


def audit_repos_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit_repos", description=(
        "Read-only audit of this machine's repositories: remotes and unfinished work."))
    _profile(parser)
    parser.add_argument("--json", action="store_true", help="machine-readable result")
    return _run(audit_repos, parser, argv)


# --------------------------------------------------------------------------- materialize

def materialize(args) -> int:
    from Special._sync.actions import apply_materialize, plan_materialize, render_materialize

    if args.apply and not args.yes:
        raise ValueError("--apply requires --yes after you review the plan")
    if not args.destination.is_dir():
        raise ValueError("--destination must already be an existing folder")
    with _locked(args):
        return _materialize(args)


def _materialize(args) -> int:
    from Special._sync.actions import apply_materialize, plan_materialize, render_materialize

    _selection, observer = _observer(args)
    count = observer.inventory()
    plan = plan_materialize(observer.paths, args.destination)
    print(f"Inventory found {count} observed repository(ies).\n{render_materialize(plan)}")
    if not args.apply:
        return 0
    results = apply_materialize(plan)
    print("\n" + render_materialize(results, applied=True))
    return 1 if any(row["action"] == "clone_failed" for row in results) else 0


def materialize_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="materialize", description=(
        "Clone this machine's observed working set into a new library folder."))
    _profile(parser)
    parser.add_argument("--destination", type=Path, required=True, help="existing empty library folder")
    parser.add_argument("--apply", action="store_true", help="clone the planned repositories")
    parser.add_argument("--yes", action="store_true", help="confirm --apply after review")
    return _run(materialize, parser, argv)


# --------------------------------------------------------------------------- list_live_buffers

def list_live_buffers(args) -> int:
    from Special._sync.selection import load_selection
    from Special._sync.vscode_buffers import default_backup_root, inspect

    selection = load_selection(args.config_dir, home=args.settings_home, roots=args.root)
    root = args.backup_root or default_backup_root()
    if root is None or not root.is_dir():
        raise ValueError("select an existing VS Code Backups folder with --backup-root")
    items = inspect(selection["roots"], root)
    print(json.dumps({"buffers": items, "note": "Explicit local metadata only; no editor buffer "
                      "content was sent or stored."}, indent=2))
    return 0


def list_live_buffers_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="list_live_buffers", description=(
        "List VS Code unsaved-buffer metadata for files under this machine's repositories."))
    _profile(parser)
    parser.add_argument("--backup-root", type=Path, help="VS Code Backups folder")
    return _run(list_live_buffers, parser, argv)


# --------------------------------------------------------------------------- enroll_machine

def _confirm(prompt_word: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise ValueError(f"confirm with --yes (no terminal to type {prompt_word})")
    return input(f"Type {prompt_word} to allow it: ").strip() == prompt_word


def enroll_machine(args) -> int:
    from Special._sync import enrollment

    home = args.settings_home
    if args.action == "add":
        paths = args.paths
        if not paths:
            if not sys.stdin.isatty():
                raise ValueError("name at least one library folder")
            answer = input("Library folder (a folder that holds your repositories): ").strip().strip('"')
            paths = [answer] if answer else []
            if not paths:
                raise ValueError("no library folder given; nothing was enrolled")
        print(enrollment.inventory_notice(paths))
        if not _confirm("SCAN", args.yes):
            print("Nothing was enrolled.")
            return 1
        roots = enrollment.add_libraries(paths, home=home, label=args.label, local_port=args.port)
        print("Libraries:\n" + "\n".join(f"  {root}" for root in roots))
        print("Start the app with App/tray.py; it inventories new libraries when it starts.")
        return 0
    if args.action == "remove":
        if len(args.paths) != 1:
            raise ValueError("remove one library at a time")
        roots = enrollment.remove_library(args.paths[0], home=home)
        print("Libraries:\n" + "\n".join(f"  {root}" for root in roots))
        return 0
    if args.action == "find":
        starts = args.paths or (enrollment.whole_machine_starts() if args.whole_machine else [])
        if not starts:
            raise ValueError("say where to look (folders), or pass --whole-machine")
        print("To suggest libraries, folder names (no file contents, no Git) are read under:\n"
              + "\n".join(f"  {start}" for start in starts)
              + f"\nup to {args.depth} levels deep. Nothing is enrolled by looking.")
        if not _confirm("LOOK", args.yes):
            print("Nothing was looked at.")
            return 1
        found = enrollment.find_libraries(starts, max_depth=args.depth)
        if not found:
            print("No repositories found there.")
            return 0
        print("Folders holding repositories (add the ones that are libraries):")
        for item in found[:40]:
            print(f"  {item['repositories']:5}  {item['path']}")
        print("Then: python Special/enroll_machine.py add <folder> [<folder> ...]")
        return 0
    if args.action == "presentation":
        chosen = enrollment.set_presentation(face=args.face, web=args.web, home=home)
        print(f"Double-clicking the tray opens: {chosen['face']}. Web view: {chosen['web']}.")
        return 0
    machine, config = enrollment.enrollment(home)
    if config is None:
        print("This machine is not enrolled. Add a library folder:\n"
              "  python Special/enroll_machine.py add <folder>\n"
              "or let it suggest some first:\n"
              "  python Special/enroll_machine.py find <folder> | --whole-machine")
        return 0
    presentation = {**enrollment.DEFAULT_PRESENTATION, **(config.get("presentation") or {})}
    shared = "joined" if config.get("transports") else "not joined (this machine only)"
    print(f"Machine: {config['label']} ({config['machine_id']})\nLibraries:\n"
          + "\n".join(f"  {root}" for root in config["roots"])
          + f"\nTray opens: {presentation['face']}. Web view: {presentation['web']}."
          + f"\nFleet: {shared}.")
    return 0


def enroll_machine_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="enroll_machine", description=(
        "Enroll this machine with the app: its library folders and how the app shows itself."))
    _profile(parser, roots=False)
    parser.add_argument("action", nargs="?", default="show",
                        choices=("show", "add", "remove", "find", "presentation"))
    parser.add_argument("paths", nargs="*", type=Path, help="library folders, or where to look")
    parser.add_argument("--yes", action="store_true", help="confirm without typing SCAN or LOOK")
    parser.add_argument("--whole-machine", action="store_true", help="find: look on every drive")
    parser.add_argument("--depth", type=int, default=4, help="find: folder levels to look through")
    parser.add_argument("--label", help="add: this machine's readable name")
    parser.add_argument("--port", type=int, help="add: the web view's local port")
    parser.add_argument("--face", choices=("web", "window"), help="what double-clicking the tray opens")
    parser.add_argument("--web", choices=("off", "loopback", "tailnet"),
                        help="serve the web view: off, this machine only, or also your tailnet devices")
    return _run(enroll_machine, parser, argv)
