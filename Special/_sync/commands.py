"""The command-line adapters behind Special's sync commands: one function per public command.

Why:          the public files in Special/ stay thin (a header, EFFECT and `main`); argument
              parsing and printing live here, the work itself in the sibling plumbing.
Reads:        see each command's own header.
May change:   see each command's own header and EFFECT.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Special: this machine, once.
Status:       working
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from Basic import _cli
from Basic._console import enable_unicode_output
from Special._settings.fleet import fleet_directory, load_fleet_settings


def _profile(parser: argparse.ArgumentParser, roots: bool = True) -> None:
    parser.add_argument("--config-dir", type=Path, help="local fleet state directory")
    parser.add_argument("--settings-home", type=Path, help="common profile; defaults to the user-data home")
    if roots:
        parser.add_argument("--root", action="append", type=Path,
                            help="observe this folder instead of the saved roots (repeatable)")


def _run(command, handler, parser, argv) -> int:
    enable_unicode_output()
    args = parser.parse_args(argv)
    try:
        return handler(args)
    except (OSError, ValueError) as exc:
        return _cli.fail(args, command, f"{exc}.")


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

def _root_specs(args, config, app=None):
    from Special._sync.observer import RootSpec

    cli_roots = [RootSpec(Path(root), args.recursive) for root in (args.root or [])]
    cli_roots += [RootSpec(Path(root), True) for root in (args.recursive_root or [])]
    if cli_roots:
        return cli_roots, "command line"
    if config and config.get("roots"):
        return ([RootSpec(Path(root["path"]), bool(root.get("recursive")))
                 for root in config["roots"]], "saved configuration")
    # The library folders setup and `gitso machine add` keep (the app's section), read the way
    # the app reads them: recursively. Without this, a machine set up by setup had "no folders".
    if app and app.get("roots"):
        return [RootSpec(Path(root), True) for root in app["roots"]], "library folders on this machine"
    return [], "nowhere"


def suggest_sync(args) -> int:
    from Special._security._advice import inspect_paths, render_advice
    from Special._sync.advice import library_tree, render_table
    from Special._sync.config import load_branches, load_catalog, load_config, merge_catalog, save_catalog
    from Special._sync.manifest import build_manifest, fleet_id_for, new_fleet_secret
    from Special._sync.observer import observe_roots

    home = args.settings_home
    config_dir = fleet_directory(args.config_dir, home=home)
    config = load_config(config_dir, home=home)
    snapshot = config.snapshot if hasattr(config, "snapshot") else load_fleet_settings(home)
    app = snapshot.config("app") if snapshot is not None and not (config and config.get("roots")) else None
    specs, source = _root_specs(args, config, app)
    identity = config or app or {}  # repository ids salted like the app's, so they match the fleet
    if snapshot is not None:
        snapshot.check_roots("sync", [spec.path for spec in specs])
    if not specs:
        raise ValueError("no folders to look at; pass --root, or enroll this machine's library folders")
    screen = not _cli.machine(args)
    if screen:
        from Basic._station import banner, line
        banner("Suggest sync", f"{len(specs)} folder(s) from the {source}")
        if args.fetch:
            line(f"Fetching remote refs for the repositories in {len(specs)} folder(s): the only network "
                 "activity, and it never touches your working tree.", "detail")
    # Repository ids only need a salt inside this run; nothing here leaves the machine.
    secret = identity.get("fleet_secret") or new_fleet_secret()

    def reading(done, total, _path):
        # One line, rewritten in place: a person sees the library being read, not a still screen.
        print(f"\r  Reading Git status: {done} of {total} repositories", end="" if done < total else "\n",
              flush=True)

    observation = observe_roots(specs, secret, fetch=args.fetch, fetch_workers=args.fetch_workers,
                                fetch_timeout=args.fetch_timeout, progress=reading if screen else None)
    # The secret check reads every working file and the outgoing history of each repository:
    # about 20 seconds a repository, over an hour for a library of 188 (2026-11-15). It is asked
    # for, not part of the status read: --security here, or the app's Security tab.
    security = inspect_paths(zip((repo["repo_id"] for repo in observation.repositories),
                                 observation.locations),
                             settings_home=home, expected_settings=snapshot) if args.security else []
    machine = identity.get("machine_id") or "this-machine"
    manifest = build_manifest(fleet_id_for(secret), machine,
                              identity.get("machine_label") or identity.get("label") or machine,
                              observation.repositories)
    merged = merge_catalog(load_catalog(config_dir), observation.catalog)
    branches = {**load_branches(config_dir), **observation.branches}
    if config and not args.no_catalog:
        save_catalog(config_dir, merged, branches)
    message = f"Looked at {len(observation.repositories)} repositories from the {source}. Nothing was published."
    record = _cli.document("machine check", manifest=manifest, local_security=security, message=message,
                           warnings=list(observation.issues), artifacts=[])

    def show():
        from Basic._station import line, notice, say
        if args.security:
            say()
            for text in render_table(manifest, merged, branches, security=security).splitlines():
                line(text)
        else:
            for text, tone in library_tree([spec.path for spec in specs], observation, everything=args.all):
                line(text, tone) if text else say()
            if not args.all:
                say()
                line("Clean repositories are counted, not listed: add --all to list every one.", "muted")
        say()
        if args.security:
            for text in render_advice(security).splitlines():
                line(text)
        else:
            line("Secrets were not checked: that reads every file (about 20 seconds a repository). Add "
                 "--security, or use the app's Security tab on the repositories you choose.", "muted")
        for issue in observation.issues:
            line(f"warning: {issue}", "warning")
        notice("Done", message, "success")

    _cli.emit(args, record, show)
    return _cli.OK


def suggest_sync_main(argv=None) -> int:
    from Special._sync.observer import DEFAULT_FETCH_TIMEOUT_SECONDS, DEFAULT_FETCH_WORKERS

    parser = _cli.parser("machine check", "Suggest what this machine's repositories need.")
    _profile(parser, roots=False)
    parser.add_argument("--root", action="append", help="folder to look at (instead of the saved ones)")
    parser.add_argument("--recursive-root", action="append", help="folder to look through recursively")
    parser.add_argument("--recursive", action="store_true", help="look through every --root recursively")
    parser.add_argument("--fetch", action="store_true",
                        help="refresh remote-tracking refs first so ahead/behind are current")
    parser.add_argument("--fetch-workers", type=int, default=DEFAULT_FETCH_WORKERS)
    parser.add_argument("--fetch-timeout", type=int, default=DEFAULT_FETCH_TIMEOUT_SECONDS)
    parser.add_argument("--no-catalog", action="store_true", help="do not update the local catalog")
    parser.add_argument("--all", action="store_true",
                        help="list every repository on the screen, not only those that need something")
    parser.add_argument("--security", action="store_true",
                        help="also check every working file and the outgoing history for secrets and "
                             "protected values (slow: about 20 seconds a repository)")
    return _run("machine check", suggest_sync, parser, argv)


# --------------------------------------------------------------------------- name_repo

def name_repo(args) -> int:
    """One explicit change, made at once (like git config): a readable name for one repository."""
    from Special._sync.config import load_catalog, save_catalog

    config_dir = fleet_directory(args.config_dir, home=args.settings_home)
    catalog = load_catalog(config_dir)
    if args.list or not args.repo_id:
        entries = [{"repo_id": repo_id, "name": entry.get("alias") or entry.get("display_name"),
                    "alias": bool(entry.get("alias"))}
                   for repo_id, entry in sorted(catalog.items(), key=lambda item: item[0])]
        return _cli.report(args, "repo list", ok=True, page="Repository names",
                           rows=[(entry["repo_id"][:12], f"{entry['name'] or '(unnamed)'}"
                                  + (" (your name)" if entry["alias"] else "")) for entry in entries],
                           message=f"{len(entries)} repositories in this machine's catalog." if entries
                           else "The catalog is empty. Run machine check first.", repositories=entries)
    if not args.name:
        raise ValueError("repo name needs both a repository id and a name (or --list)")
    matches = [repo_id for repo_id in catalog if repo_id.startswith(args.repo_id)]
    if len(matches) != 1:
        raise ValueError(f"{'no' if not matches else 'more than one'} repository id starts with {args.repo_id!r}")
    catalog[matches[0]] = {**catalog[matches[0]], "alias": args.name}
    save_catalog(config_dir, catalog)
    return _cli.report(args, "repo name", ok=True, page="Repository names", rows=[(matches[0][:12], args.name)],
                       message="Named. The name stays on this machine.", repo_id=matches[0], name=args.name)


def name_repo_main(argv=None) -> int:
    parser = _cli.parser("repo name", "Name a repository in this machine's local catalog.")
    _profile(parser, roots=False)
    parser.add_argument("repo_id", nargs="?", help="repository id, or the start of one")
    parser.add_argument("name", nargs="?", help="readable name to show for it")
    parser.add_argument("--list", action="store_true", help="list the catalog")
    return _run("repo name", name_repo, parser, argv)


# --------------------------------------------------------------------------- catch_up

def catch_up(args, argv) -> int:
    with _locked(args):
        return _catch_up(args, argv)


def _catch_up(args, argv) -> int:
    from Special._sync.actions import apply_catchup, plan_catchup, render_catchup

    _selection, observer = _observer(args)
    count = observer.inventory()
    if not _cli.machine(args):
        from Basic._station import banner, line
        banner("Catch up", f"{count} repositories")
        line("Fetching their remotes; branches, indexes and files are not changed.", "detail")
    plan = plan_catchup(observer.paths)
    approval = _cli.Approval(args, "catch-up", argv)

    def show():
        from Basic._station import line, say
        say()
        for text in render_catchup(plan).splitlines():
            line(text)

    safe = [item for item in plan if item["action"] == "pull"]
    if not approval.decide(plan, show, nothing_to_do=not safe,
                           question=f"Fast-forward these {len(safe)} checkouts?"):
        return approval.code
    results = apply_catchup(plan)
    failed = any(item["action"] in {"fetch_failed", "pull_failed", "pull_needs_review"} for item in results)
    return _cli.report(args, "catch-up", ok=not failed, page="Catch up  /  Done",
                       output=render_catchup(results, applied=True),
                       message="Some checkouts need a look; see above." if failed else "Caught up.",
                       results=[{**item, "path": str(item["path"])} for item in results])


def catch_up_main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser("catch-up", "Fetch every observed repository, then fast-forward the clean, "
                                     "behind-only checkouts; shows the plan first.")
    _profile(parser)
    _cli.add_apply(parser)
    return _run("catch-up", lambda args: catch_up(args, argv), parser, argv)


# --------------------------------------------------------------------------- audit_repos

def audit_repos(args) -> int:
    from Special._sync.actions import audit_repositories, every_repository, render_audit
    from Special._sync.selection import load_selection

    selection = load_selection(args.config_dir, home=args.settings_home, roots=args.root,
                               allow_unavailable=True)
    # Its own walk, not the observer's inventory: that drops the repositories without an origin
    # which are exactly what an audit exists to find.
    hits, problems = every_repository(selection["roots"])
    rows = [{"path": row["path"], "name": row["name"], "origin": None,
             "findings": [row["detail"]]} for row in problems]
    rows += [{"path": Path(hit.path), "name": Path(hit.path).name, "origin": None,
              "findings": ["bare repository (not audited)"]} for hit in hits if hit.kind == "bare"]
    rows += audit_repositories([hit.path for hit in hits if hit.kind != "bare"])
    attention = any(item["findings"] != ["no audited issue"] for item in rows)
    _cli.report(args, "machine audit", ok=not attention, page="Audit repositories",
                output=render_audit(rows),
                message=f"Looked at {len(hits)} repositories; " +
                        ("some need attention." if attention else "nothing needs attention."),
                repositories=[{**row, "path": str(row["path"])} for row in rows])
    return 1 if attention else 0


def audit_repos_main(argv=None) -> int:
    parser = _cli.parser("machine audit", "Read-only audit of this machine's repositories: remotes and "
                                        "unfinished work.")
    _profile(parser)
    return _run("machine audit", audit_repos, parser, argv)


# --------------------------------------------------------------------------- materialize

def materialize(args, argv) -> int:
    if not args.destination.is_dir():
        raise ValueError("--destination must already be an existing folder")
    with _locked(args):
        return _materialize(args, argv)


def _materialize(args, argv) -> int:
    from Special._sync.actions import apply_materialize, plan_materialize, render_materialize

    _selection, observer = _observer(args)
    observer.inventory()
    plan = plan_materialize(observer.paths, args.destination)
    approval = _cli.Approval(args, "materialize", argv)

    def show():
        from Basic._station import banner, line, say
        banner("Materialize", str(args.destination))
        say()
        for text in render_materialize(plan).splitlines():
            line(text)

    clones = [row for row in plan if row["action"] == "clone"]
    if not approval.decide(plan, show, nothing_to_do=not clones,
                           question=f"Clone these {len(clones)} repositories?"):
        return approval.code
    results = apply_materialize(plan)
    failed = any(row["action"] == "clone_failed" for row in results)
    return _cli.report(args, "materialize", ok=not failed, page="Materialize  /  Done",
                       context=(str(args.destination),), output=render_materialize(results, applied=True),
                       message="Some clones failed; see above." if failed else "Cloned.",
                       results=[{key: str(value) if isinstance(value, Path) else value
                                 for key, value in row.items()} for row in results])


def materialize_main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser("materialize", "Clone this machine's observed working set into a new library "
                                        "folder; shows the plan first.")
    _profile(parser)
    parser.add_argument("--destination", type=Path, required=True, help="an existing, empty library folder")
    _cli.add_apply(parser)
    return _run("materialize", lambda args: materialize(args, argv), parser, argv)


# --------------------------------------------------------------------------- list_live_buffers

def list_live_buffers(args) -> int:
    from Special._sync.selection import load_selection
    from Special._sync.observer import library_available
    from Special._sync.vscode_buffers import default_backup_root, inspect

    selection = load_selection(args.config_dir, home=args.settings_home, roots=args.root,
                               allow_unavailable=True)
    root = args.backup_root or default_backup_root()
    if root is None or not root.is_dir():
        raise ValueError("select an existing VS Code Backups folder with --backup-root")
    available = [path for path in selection["roots"] if library_available(path)]
    unavailable = [path for path in selection["roots"] if path not in available]
    items = inspect(available, root) if available else []
    return _cli.report(args, "machine buffers", ok=not unavailable, page="Unsaved editor buffers", context=(str(root),),
                       rows=[(Path(str(item.get("path", ""))).name or "buffer", item.get("path", ""))
                             for item in items],
                       message="Local metadata only; no editor buffer content was read out, sent or stored."
                               + (" Unavailable libraries: " + ", ".join(unavailable) if unavailable else ""),
                       buffers=items, unavailable_libraries=unavailable)


def list_live_buffers_main(argv=None) -> int:
    parser = _cli.parser("machine buffers", "List VS Code unsaved-buffer metadata for files under "
                                              "this machine's repositories.")
    _profile(parser)
    parser.add_argument("--backup-root", type=Path, help="VS Code Backups folder")
    return _run("machine buffers", list_live_buffers, parser, argv)


# --------------------------------------------------------------------------- enroll_machine

def enroll_machine(args, argv) -> int:
    from Special._sync import enrollment

    home = args.settings_home
    approval = _cli.Approval(args, "machine", argv)
    if args.action == "add":
        paths = args.paths
        if not paths:
            if not _cli.interactive(args):
                raise ValueError("name at least one library folder")
            from Basic._station import ask
            answer = ask("Library folder (a folder that holds your repositories):").strip('"')
            paths = [Path(answer)] if answer else []
            if not paths:
                raise ValueError("no library folder given; nothing was enrolled")
        plan = {"action": "add", "libraries": [str(Path(path).expanduser().resolve()) for path in paths],
                "label": args.label, "port": args.port}

        def show():
            from Basic._station import banner, line, say
            banner("Enroll this machine  /  Add libraries")
            say()
            for text in enrollment.inventory_notice(paths).splitlines():
                line(text)

        if not approval.decide(plan, show, question="Enroll these library folders?"):
            return approval.code
        roots = enrollment.add_libraries(paths, home=home, label=args.label, local_port=args.port)
        return _cli.report(args, "machine", ok=True, page="Enroll this machine",
                           rows=[("Library", root) for root in roots],
                           message="Enrolled. Start the app (gitso tray); it looks through new libraries "
                                   "when it starts.", libraries=roots)
    if args.action == "remove":
        if len(args.paths) != 1:
            raise ValueError("remove one library at a time")
        roots = enrollment.remove_library(args.paths[0], home=home)
        return _cli.report(args, "machine", ok=True, page="Enroll this machine",
                           rows=[("Library", root) for root in roots],
                           message="Removed. Nothing in that folder was touched.", libraries=roots)
    if args.action == "find":
        starts = args.paths or (enrollment.whole_machine_starts() if args.whole_machine else [])
        if not starts:
            raise ValueError("say where to look (folders), or pass --whole-machine")
        plan = {"action": "find", "look_under": [str(start) for start in starts], "depth": args.depth}

        def show_look():
            from Basic._station import banner, line, row, say
            banner("Enroll this machine  /  Find libraries")
            say()
            line("To suggest library folders, gitSpecOps reads folder names (no file contents, no Git) "
                 f"under these, up to {args.depth} levels deep. Nothing is enrolled by looking.")
            for start in starts:
                row("Look under", start)

        if not approval.decide(plan, show_look, question="Look there?"):
            return approval.code
        found = enrollment.find_libraries(starts, max_depth=args.depth)
        return _cli.report(args, "machine", ok=True, page="Enroll this machine  /  Found",
                           rows=[(f"{item['repositories']} repos", item["path"]) for item in found[:40]],
                           message=("Add the ones that are libraries: gitso machine add FOLDER ..."
                                    if found else "No repositories found there."),
                           found=[{**item, "path": str(item["path"])} for item in found])
    if args.action == "presentation":
        chosen = enrollment.set_presentation(face=args.face, web=args.web, home=home)
        return _cli.report(args, "machine", ok=True, page="Enroll this machine",
                           rows=[("Tray opens", chosen["face"]), ("Web view", chosen["web"])],
                           message="Saved.", presentation=chosen)
    machine, config = enrollment.enrollment(home)
    if config is None:
        return _cli.report(args, "machine", ok=True, page="Enroll this machine",
                           message="This machine is not enrolled. Add a library folder: "
                                   "gitso machine add FOLDER (or find FOLDER to get suggestions).",
                           enrolled=False)
    presentation = {**enrollment.DEFAULT_PRESENTATION, **(config.get("presentation") or {})}
    shared = "joined" if config.get("transports") else "not joined (this machine only)"
    return _cli.report(args, "machine", ok=True, page="Enroll this machine",
                       rows=[("Machine", f"{config['label']} ({config['machine_id']})"),
                             *(("Library", root) for root in config["roots"]),
                             ("Tray opens", presentation["face"]), ("Web view", presentation["web"]),
                             ("Fleet", shared)],
                       message="Enrolled.", enrolled=True, machine=config["label"],
                       machine_id=config["machine_id"], libraries=list(config["roots"]),
                       presentation=presentation, fleet=shared)


def enroll_machine_main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _cli.parser("machine", "Enroll this machine: its library folders and how the app "
                                           "shows itself.")
    _profile(parser, roots=False)
    parser.add_argument("action", nargs="?", default="show",
                        choices=("show", "add", "remove", "find", "presentation"))
    parser.add_argument("paths", nargs="*", type=Path, help="library folders, or where to look")
    parser.add_argument("--whole-machine", action="store_true", help="find: look on every drive")
    parser.add_argument("--depth", type=int, default=4, help="find: folder levels to look through")
    parser.add_argument("--label", help="add: this machine's readable name")
    parser.add_argument("--port", type=int, help="add: the web view's local port")
    parser.add_argument("--face", choices=("web", "window"), help="what double-clicking the tray opens")
    parser.add_argument("--web", choices=("off", "loopback", "tailnet"),
                        help="serve the web view: off, this machine only, or also your tailnet devices")
    _cli.add_apply(parser)
    return _run("machine", lambda args: enroll_machine(args, argv), parser, argv)
