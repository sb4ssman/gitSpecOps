#!/usr/bin/env python3
"""Read-only cross-machine Git status observer and advisor.

Nothing in this tool pulls, pushes, commits, stashes, or otherwise touches an observed
repository. It reads local Git facts inside explicitly registered roots, publishes a
privacy-minimized status manifest for this machine into a folder the user's own sync
client replicates, and reads the manifests other machines left there.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from advice import render_table
from aggregate import (build_rows, load_manifests, machine_views, render_dashboard,
                       split_by_fleet)
from convergence import (
    catalog_updates,
    missing_from,
    namespaces_from_catalog,
    render_report,
    resolve_missing,
    roots_by_owner,
)
from config import (
    default_config,
    default_config_dir,
    load_branches,
    load_catalog,
    load_config,
    merge_catalog,
    roots_from_archive_registry,
    save_catalog,
    save_config,
    validate_config,
)
from folder_transport import FolderTransport
from repo_transport import RepoTransport, create_state_repo, repo_exists
from convergence import MissingRepo  # noqa: E402  (dataclass used in --no-resolve)
from manifest import build_manifest, fleet_id_for, is_fleet_secret
from observer import (DEFAULT_FETCH_TIMEOUT_SECONDS, DEFAULT_FETCH_WORKERS, RootSpec,
                      observe_roots)
from watcher import DEFAULT_HEARTBEAT_SECONDS, DEFAULT_INTERVAL_SECONDS, run_watch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.providers import provider_for_host, registered_hosts  # noqa: E402
PREVIEW_MACHINE_ID = "local-preview"


def open_transport(config: dict | None, args: argparse.Namespace | None = None):
    """Return (transport, label) for whichever transport is configured, or (None, None).

    Flags beat saved configuration, and a repo beats a folder when both are somehow given
    on the command line — but the saved configuration can never hold both, so the normal
    case is unambiguous.
    """
    config = config or {}
    spec = getattr(args, "state_repo", None) or config.get("state_repo")
    if spec:
        return RepoTransport(spec), f"repo {spec}"
    folder = getattr(args, "state_dir", None) or config.get("state_dir")
    if folder:
        return FolderTransport(folder), f"folder {folder}"
    return None, None


def _config_dir(args: argparse.Namespace) -> Path:
    return Path(args.config_dir).expanduser() if args.config_dir else default_config_dir()


def _not_ready(command: str) -> int:
    print(f"'{command}' is not implemented yet; it moves work between machines and needs its "
          "own design pass. Use 'check', 'watch', 'dashboard', 'converge', 'alias', "
          "or 'doctor'.")
    return 2


def _root_specs(args: argparse.Namespace, config: dict | None) -> tuple[list[RootSpec], str]:
    """CLI roots win outright; otherwise fall back to the registered roots from `init`."""
    cli_roots = [RootSpec(Path(root), args.recursive) for root in (args.root or [])]
    cli_roots += [RootSpec(Path(root), True) for root in (args.recursive_root or [])]
    if cli_roots:
        return cli_roots, "command line"
    if config and config["roots"]:
        return ([RootSpec(Path(root["path"]), bool(root.get("recursive")))
                 for root in config["roots"]], "saved configuration")
    return [], "nowhere"


def command_init(args: argparse.Namespace) -> int:
    config_dir = _config_dir(args)
    existing = None
    try:
        existing = load_config(config_dir)
    except ValueError as exc:
        print(f"warning: existing config is unusable, it will be replaced: {exc}", file=sys.stderr)
    if existing and not args.force:
        print(f"Configuration already exists: {config_dir}\n"
              "Re-run with --force to replace it, or edit the file directly.", file=sys.stderr)
        return 2

    if args.fleet_secret and not is_fleet_secret(args.fleet_secret):
        print("error: --fleet-secret must be 64 hexadecimal characters (copy it from the "
              "machine that created the fleet)", file=sys.stderr)
        return 2
    config = default_config(args.machine_id, args.fleet_secret)
    if args.machine_label:
        config["machine_label"] = args.machine_label
    if args.state_dir and args.state_repo:
        print("error: choose either --state-dir or --state-repo, not both.", file=sys.stderr)
        return 2
    if args.state_dir:
        config["state_dir"] = str(Path(args.state_dir).expanduser())
    if args.state_repo:
        try:
            RepoTransport(args.state_repo)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        config["state_repo"] = args.state_repo
        if not repo_exists(args.state_repo):
            if not args.create_state_repo:
                print(f"error: {args.state_repo} does not exist or is not visible to your gh "
                      "login. Re-run with --create-state-repo to create it as a private "
                      "repository.", file=sys.stderr)
                return 2
            print(f"Creating private repository {args.state_repo} ...")
            create_state_repo(args.state_repo)
            print("Created.")
        health = RepoTransport(args.state_repo).doctor()
        if health.get("private") is False and not args.allow_public_state_repo:
            # Refused, not warned. Machine status in a public repository is readable by
            # anyone, and branch names alone say a great deal about what you are working on.
            print(f"error: {args.state_repo} is PUBLIC. Machine status there would be visible "
                  "to anyone, including your branch names. Use a private repository, or pass "
                  "--allow-public-state-repo if you genuinely intend that.", file=sys.stderr)
            return 2
        if health.get("private") is False:
            print(f"warning: publishing machine status to the PUBLIC repo {args.state_repo} "
                  "because --allow-public-state-repo was given", file=sys.stderr)
        if health.get("permissions") is False:
            print(f"error: your gh login cannot write to {args.state_repo}.", file=sys.stderr)
            return 2
    if args.stale_hours is not None:
        config["stale_hours"] = args.stale_hours
    if args.expired_days is not None:
        config["expired_days"] = args.expired_days

    roots: list[dict] = []
    seen: set[str] = set()
    def add_root(path: str, recursive: bool) -> None:
        resolved = str(Path(path).expanduser())
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append({"path": resolved, "recursive": recursive})

    for path in args.root or []:
        add_root(path, False)
    for path in args.recursive_root or []:
        add_root(path, True)
    if args.from_archives:
        imported = roots_from_archive_registry(REPO_ROOT)
        for path in imported:
            add_root(path, False)
        print(f"Imported {len(imported)} root(s) from the archive registry.")
    config["roots"] = roots

    try:
        validate_config(config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not roots:
        print("warning: no roots registered — 'check' will need --root until you add some.",
              file=sys.stderr)
    for root in roots:
        if not Path(root["path"]).is_dir():
            print(f"warning: root does not exist yet: {root['path']}", file=sys.stderr)

    written = save_config(config_dir, config)
    print(f"Configuration written: {written}")
    shown = {**config, "fleet_secret": "(hidden — see below)"}
    print(json.dumps(shown, indent=2, sort_keys=True))
    print()
    if args.fleet_secret:
        print(f"Joined fleet {fleet_id_for(config['fleet_secret'])}.")
    else:
        print(f"Created fleet {fleet_id_for(config['fleet_secret'])}. To add another machine, "
              "run init there with:")
        print(f"\n    --fleet-secret {config['fleet_secret']}\n")
        print("Carry that value yourself (password manager, typed by hand). Do NOT put it in the "
              "state directory — the secret is what stops anyone who obtains that folder from "
              "recovering which repositories you have.")
    return 0


class Resolution:
    """What `check` and `watch` both need: where to look, who we are, where to publish."""

    def __init__(self, config_dir: Path, config: dict | None, specs: list[RootSpec],
                 source: str, machine_id: str, machine_label: str, state_dir: str | None,
                 transport=None, transport_label: str | None = None):
        self.config_dir, self.config = config_dir, config
        self.specs, self.source = specs, source
        self.machine_id, self.machine_label = machine_id, machine_label
        self.state_dir = state_dir
        self.transport, self.transport_label = transport, transport_label

    @property
    def secret(self) -> str | None:
        return (self.config or {}).get("fleet_secret")

    @property
    def fleet_id(self) -> str | None:
        return fleet_id_for(self.secret) if self.secret else None


def _resolve(args: argparse.Namespace) -> Resolution | int:
    """Flags beat saved configuration beats a preview default. Returns an exit code on error."""
    config_dir = _config_dir(args)
    try:
        config = load_config(config_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    specs, source = _root_specs(args, config)
    if not specs:
        print("error: no roots to observe. Run 'init --root PATH' or pass --root.", file=sys.stderr)
        return 2
    transport, transport_label = open_transport(config, args)
    state_dir = transport_label  # kept for messages; publication goes through `transport`
    machine_id = args.machine_id or (config or {}).get("machine_id") or PREVIEW_MACHINE_ID
    # An explicit --machine-id with no label should label itself, not inherit the saved label.
    machine_label = (args.machine_label
                     or (None if args.machine_id else (config or {}).get("machine_label"))
                     or machine_id)
    if state_dir and not (config or {}).get("fleet_secret"):
        # Without a fleet secret the identities would be unsalted, which is exactly the v1
        # weakness v2 exists to close. Refuse rather than publish a weaker manifest.
        print("error: publishing needs a fleet secret — run 'init' on this machine first "
              "(add --fleet-secret to join an existing fleet)", file=sys.stderr)
        return 2
    if state_dir and machine_id == PREVIEW_MACHINE_ID:
        print("error: publishing needs a real machine id — run 'init' or pass --machine-id",
              file=sys.stderr)
        return 2
    return Resolution(config_dir, config, specs, source, machine_id, machine_label, state_dir,
                      transport, transport_label)


def command_check(args: argparse.Namespace) -> int:
    resolved = _resolve(args)
    if isinstance(resolved, int):
        return resolved
    config_dir, config = resolved.config_dir, resolved.config
    specs, source = resolved.specs, resolved.source
    transport, machine_id, machine_label = (resolved.transport, resolved.machine_id,
                                            resolved.machine_label)

    if args.fetch:
        print(f"Fetching remote refs for repositories in {len(specs)} root(s) — this is the "
              "only network activity check performs, and it never touches your working tree.")

    def progress(done, total, path):
        if args.fetch and (done == total or done % 25 == 0):
            print(f"  … {done}/{total} observed", file=sys.stderr)

    observation = observe_roots(specs, resolved.secret, fetch=args.fetch,
                                fetch_workers=args.fetch_workers,
                                fetch_timeout=args.fetch_timeout, progress=progress)
    manifest = build_manifest(resolved.fleet_id or "preview", machine_id, machine_label,
                              observation.repositories)

    catalog = load_catalog(config_dir)
    merged = merge_catalog(catalog, observation.catalog)
    branches = {**load_branches(config_dir), **observation.branches}
    if config and not args.no_catalog:
        save_catalog(config_dir, merged, branches)

    published = None
    if transport is not None and not args.no_publish:
        published = transport.write_own_manifest(machine_id, manifest)

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    elif transport is not None and not args.local_only:
        print(_dashboard_text(transport, config, merged, own=manifest, show_all=args.all))
    else:
        print(render_table(manifest, merged, branches))

    print(f"\nObserved {len(observation.repositories)} repositor(ies) from {source}.")
    if published:
        print(f"Manifest written: {published}")
    for issue in observation.issues:
        print(f"warning: {issue}", file=sys.stderr)
    return 0


def command_watch(args: argparse.Namespace) -> int:
    resolved = _resolve(args)
    if isinstance(resolved, int):
        return resolved
    if resolved.transport is None:
        print("error: watch publishes, so it needs somewhere to publish to. "
              "Run 'init --state-dir PATH' or 'init --state-repo owner/name'.", file=sys.stderr)
        return 2
    transport = resolved.transport
    # An Event rather than a flag so a signal arriving mid-interval wakes the sleep at once
    # instead of waiting it out — the last observation is the one worth not missing.
    stopping = threading.Event()

    def request_stop(signum, _frame):
        # Second signal wins outright; the first one asks the loop to finish its cycle.
        if stopping.is_set():
            raise KeyboardInterrupt
        stopping.set()
        print(f"\nsignal {signum} received — publishing a final observation, then stopping.")

    def observe() -> dict:
        observation = observe_roots(resolved.specs, resolved.secret, fetch=args.fetch,
                                    fetch_workers=args.fetch_workers,
                                    fetch_timeout=args.fetch_timeout)
        if resolved.config and not args.no_catalog:
            save_catalog(resolved.config_dir,
                         merge_catalog(load_catalog(resolved.config_dir), observation.catalog),
                         observation.branches)
        return build_manifest(resolved.fleet_id, resolved.machine_id, resolved.machine_label,
                              observation.repositories)

    for name in ("SIGINT", "SIGTERM"):
        handler = getattr(signal, name, None)
        if handler is not None:
            signal.signal(handler, request_stop)

    print(f"Watching {len(resolved.specs)} root(s) from {resolved.source} "
          f"every {args.interval}s (heartbeat {args.heartbeat}s). Ctrl-C to stop.")
    result = run_watch(
        observe,
        lambda manifest: transport.write_own_manifest(resolved.machine_id, manifest),
        interval=args.interval,
        heartbeat=args.heartbeat,
        once=args.once,
        max_cycles=args.cycles,
        should_stop=stopping.is_set,
        sleeper=stopping.wait,
    )
    print(f"Stopped after {result.cycles} cycle(s), {result.publishes} publication(s).")
    for error in result.errors:
        print(f"warning: {error}", file=sys.stderr)
    return 1 if result.errors and result.publishes == 0 else 0


def _dashboard_text(transport, config: dict | None, catalog: dict[str, dict],
                    own: dict | None = None, show_all: bool = False) -> str:
    manifests, issues = load_manifests(transport)
    if own is not None:
        manifests = [m for m in manifests if m.get("machine_id") != own["machine_id"]] + [own]
    secret = (config or {}).get("fleet_secret")
    manifests, foreign = split_by_fleet(manifests, fleet_id_for(secret) if secret else None)
    stale_hours = (config or {}).get("stale_hours", 24)
    expired_days = (config or {}).get("expired_days", 7)
    now = datetime.now(timezone.utc)
    views = sorted(machine_views(manifests, now, stale_hours, expired_days),
                   key=lambda view: (own is None or view.machine_id != own["machine_id"],
                                     view.label.lower()))
    text = render_dashboard(views, build_rows(views, catalog), now, show_all=show_all,
                            foreign=foreign, stale_hours=stale_hours,
                            expired_days=expired_days)
    for issue in issues:
        print(f"warning: {issue}", file=sys.stderr)
    return text


def command_dashboard(args: argparse.Namespace) -> int:
    config_dir = _config_dir(args)
    try:
        config = load_config(config_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    transport, label = open_transport(config, args)
    if transport is None:
        print("error: no state location. Run 'init --state-dir PATH' or "
              "'init --state-repo owner/name'.", file=sys.stderr)
        return 2
    print(_dashboard_text(transport, config, load_catalog(config_dir), show_all=args.all))
    return 0


def command_alias(args: argparse.Namespace) -> int:
    """Name a repository this machine has never cloned, so peer rows stay readable."""
    config_dir = _config_dir(args)
    catalog = load_catalog(config_dir)
    if args.list or not args.repo_id:
        for repo_id, entry in sorted(catalog.items(), key=lambda item: item[0]):
            name = entry.get("alias") or entry.get("display_name") or "(unnamed)"
            marker = " (alias)" if entry.get("alias") else ""
            print(f"{repo_id[:12]}  {name}{marker}")
        if not catalog:
            print("Catalog is empty. Run 'check' first.")
        return 0
    matches = [repo_id for repo_id in catalog if repo_id.startswith(args.repo_id)]
    if len(matches) != 1:
        print(f"error: {'no' if not matches else 'ambiguous'} repo id for {args.repo_id!r}",
              file=sys.stderr)
        return 2
    catalog[matches[0]] = {**catalog[matches[0]], "alias": args.name}
    save_catalog(config_dir, catalog)
    print(f"{matches[0][:12]} -> {args.name}")
    return 0


def command_converge(args: argparse.Namespace) -> int:
    """Report which repositories peers have that this machine does not, and name them.

    Read-only, including the network calls: it lists namespaces through the provider seam and
    never clones. Cloning belongs to `archive_sync.py`, which already does it safely.
    """
    config_dir = _config_dir(args)
    try:
        config = load_config(config_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not config:
        print("error: converge needs this machine's configuration. Run 'init' first.",
              file=sys.stderr)
        return 2
    transport, _label = open_transport(config, args)
    if transport is None:
        print("error: no state location to read peer reports from.", file=sys.stderr)
        return 2

    secret = config["fleet_secret"]
    manifests, issues = load_manifests(transport)
    manifests, foreign = split_by_fleet(manifests, fleet_id_for(secret))
    for issue in issues:
        print(f"warning: {issue}", file=sys.stderr)
    for manifest in foreign:
        print(f"warning: {manifest.get('machine_label') or manifest['machine_id']} is on a "
              f"different fleet secret and was excluded", file=sys.stderr)

    now = datetime.now(timezone.utc)
    views = machine_views(manifests, now, config["stale_hours"], config["expired_days"])
    if not any(view.machine_id == config["machine_id"] for view in views):
        print("error: this machine has not published yet — run 'check' first, otherwise every "
              "repository would look missing.", file=sys.stderr)
        return 2

    missing = missing_from(views, config["machine_id"])
    catalog = load_catalog(config_dir)
    if args.namespace:
        namespaces = [(args.host, owner) for owner in args.namespace]
    else:
        namespaces = namespaces_from_catalog(catalog)

    resolved, errors = ([], [])
    if missing and not args.no_resolve:
        _register_providers()
        def progress(host, owner, remaining):
            print(f"  … listing {host}/{owner} ({remaining} still unnamed)", file=sys.stderr)
        resolved, errors = resolve_missing(missing, namespaces, secret, provider_for_host,
                                           known=catalog, progress=progress)
        updates = catalog_updates(resolved)
        if updates and not args.no_catalog:
            save_catalog(config_dir, merge_catalog(catalog, updates))
    elif missing:
        resolved = [MissingRepo(repo_id=repo_id, machines=machines)
                    for repo_id, machines in missing.items()]

    print(render_report(resolved, errors, namespaces, roots_by_owner(catalog)))
    return 0


def _register_providers() -> None:
    """Import the tool-side providers so the shared registry is populated.

    `shared/` never imports tool folders, so somebody has to do this; for the archive tools it
    happens at their own import time. Failing to load one host must not stop the others.
    """
    sys.path.insert(0, str(REPO_ROOT / "git-archive-updater"))
    # remote_provider.py is the module that calls register_provider(); importing the
    # provider class alone registers nothing.
    try:
        import remote_provider  # noqa: F401
    except ImportError as exc:
        print(f"warning: GitHub provider unavailable: {exc}", file=sys.stderr)
    if not registered_hosts():
        print("warning: no remote providers registered; unknown repositories cannot be named",
              file=sys.stderr)


def command_doctor(args: argparse.Namespace) -> int:
    config_dir = _config_dir(args)
    report: dict = {"config_dir": str(config_dir)}
    try:
        config = load_config(config_dir)
        report["config"] = config
        report["config_error"] = None
    except ValueError as exc:
        config, report["config"], report["config_error"] = None, None, str(exc)
    if report.get("config"):
        # The fleet id is a public label; the secret itself must never be printed.
        report["config"] = {**report["config"], "fleet_secret": "(set, hidden)"}
        report["fleet_id"] = fleet_id_for((config or {}).get("fleet_secret"))
    report["catalog_entries"] = len(load_catalog(config_dir))
    transport, label = open_transport(config, args)
    report["state"] = label
    if transport is not None:
        report["transport"] = transport.doctor()
        manifests, issues = load_manifests(transport)
        report["machines"] = sorted(m["machine_id"] for m in manifests)
        report["foreign_fleet_machines"] = sorted(
            m["machine_id"] for m in manifests
            if report.get("fleet_id") and m.get("fleet_id") != report["fleet_id"])
        report["manifest_issues"] = issues
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config-dir", help="override the local state directory "
                                             f"(default: {default_config_dir()})")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="write this machine's saved configuration")
    init.add_argument("--machine-id", help="stable non-personal id (default: this hostname)")
    init.add_argument("--fleet-secret",
                      help="join an existing fleet (64 hex chars, printed by the first machine); "
                           "omit to create a new fleet")
    init.add_argument("--machine-label", help="readable label (default: the machine id)")
    init.add_argument("--root", action="append", help="root scanned by direct children (repeatable)")
    init.add_argument("--recursive-root", action="append",
                      help="root scanned recursively (repeatable)")
    init.add_argument("--state-dir", help="folder your sync client replicates between machines")
    init.add_argument("--state-repo",
                      help="private GitHub repo (owner/name) to hold machine state instead of "
                           "a folder; read/written through your existing gh login, never cloned")
    init.add_argument("--create-state-repo", action="store_true",
                      help="with --state-repo, create it as a private repository if missing")
    init.add_argument("--allow-public-state-repo", action="store_true",
                      help="permit a PUBLIC state repository (refused by default: anyone could "
                           "read your machine status and branch names)")
    init.add_argument("--from-archives", action="store_true",
                      help="also register roots from the archive updater's local registry")
    init.add_argument("--stale-hours", type=int, help="report older than this is stale (default 24)")
    init.add_argument("--expired-days", type=int, help="report older than this is expired (default 7)")
    init.add_argument("--force", action="store_true", help="replace an existing configuration")
    init.set_defaults(handler=command_init)

    check = subparsers.add_parser("check", help="observe roots, publish, and show the dashboard")
    check.add_argument("--root", action="append", help="root to inspect (overrides saved roots)")
    check.add_argument("--recursive-root", action="append", help="recursive root (overrides saved)")
    check.add_argument("--recursive", action="store_true", help="scan every --root recursively")
    check.add_argument("--machine-id", help="override the saved machine id")
    check.add_argument("--machine-label", help="override the saved readable label")
    check.add_argument("--state-dir", help="override the saved manifest folder")
    check.add_argument("--state-repo", help="override the saved state repository (owner/name)")
    check.add_argument("--local-only", action="store_true", help="skip peers; show this machine only")
    check.add_argument("--all", action="store_true", help="list every repository, not just exceptions")
    check.add_argument("--no-publish", action="store_true", help="observe without writing a manifest")
    check.add_argument("--no-catalog", action="store_true", help="do not update the local catalog")
    check.add_argument("--fetch", action="store_true",
                       help="refresh remote-tracking refs first so ahead/behind are current "
                            "(the only network activity; never touches the working tree)")
    check.add_argument("--fetch-workers", type=int, default=DEFAULT_FETCH_WORKERS,
                       help=f"parallel fetches (default {DEFAULT_FETCH_WORKERS})")
    check.add_argument("--fetch-timeout", type=int, default=DEFAULT_FETCH_TIMEOUT_SECONDS,
                       help=f"seconds per fetch (default {DEFAULT_FETCH_TIMEOUT_SECONDS})")
    check.add_argument("--json", action="store_true", help="print the privacy-minimized manifest")
    check.set_defaults(handler=command_check)

    dashboard = subparsers.add_parser("dashboard", help="read peer manifests without observing")
    dashboard.add_argument("--state-dir", help="override the saved manifest folder")
    dashboard.add_argument("--state-repo", help="override the saved state repository (owner/name)")
    dashboard.add_argument("--all", action="store_true", help="list every repository, not just exceptions")
    dashboard.set_defaults(handler=command_dashboard)

    alias = subparsers.add_parser("alias", help="name a repository in the local-only catalog")
    alias.add_argument("repo_id", nargs="?", help="repo id or unique prefix")
    alias.add_argument("name", nargs="?", help="readable name to show for it")
    alias.add_argument("--list", action="store_true", help="list catalog entries")
    alias.set_defaults(handler=command_alias)

    doctor = subparsers.add_parser("doctor", help="inspect local state and transport, changing nothing")
    doctor.add_argument("--state-dir", help="override the saved manifest folder")
    doctor.add_argument("--state-repo", help="override the saved state repository (owner/name)")
    doctor.set_defaults(handler=command_doctor)

    watch = subparsers.add_parser("watch", help="keep observing and republish when facts change")
    watch.add_argument("--root", action="append", help="root to inspect (overrides saved roots)")
    watch.add_argument("--recursive-root", action="append", help="recursive root (overrides saved)")
    watch.add_argument("--recursive", action="store_true", help="scan every --root recursively")
    watch.add_argument("--machine-id", help="override the saved machine id")
    watch.add_argument("--machine-label", help="override the saved readable label")
    watch.add_argument("--state-dir", help="override the saved manifest folder")
    watch.add_argument("--state-repo", help="override the saved state repository (owner/name)")
    watch.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS,
                       help=f"seconds between observations (default {DEFAULT_INTERVAL_SECONDS})")
    watch.add_argument("--heartbeat", type=float, default=DEFAULT_HEARTBEAT_SECONDS,
                       help="seconds before republishing unchanged facts "
                            f"(default {DEFAULT_HEARTBEAT_SECONDS})")
    watch.add_argument("--once", action="store_true", help="run a single cycle and exit")
    watch.add_argument("--cycles", type=int, help="stop after this many cycles")
    watch.add_argument("--fetch", action="store_true",
                       help="refresh remote-tracking refs first so ahead/behind are current "
                            "(the only network activity; never touches the working tree)")
    watch.add_argument("--fetch-workers", type=int, default=DEFAULT_FETCH_WORKERS,
                       help=f"parallel fetches (default {DEFAULT_FETCH_WORKERS})")
    watch.add_argument("--fetch-timeout", type=int, default=DEFAULT_FETCH_TIMEOUT_SECONDS,
                       help=f"seconds per fetch (default {DEFAULT_FETCH_TIMEOUT_SECONDS})")
    watch.add_argument("--no-catalog", action="store_true", help="do not update the local catalog")
    watch.set_defaults(handler=command_watch)

    converge = subparsers.add_parser(
        "converge", help="report repositories peers have that this machine does not")
    converge.add_argument("--state-dir", help="override the saved manifest folder")
    converge.add_argument("--state-repo", help="override the saved state repository (owner/name)")
    converge.add_argument("--namespace", action="append",
                          help="owner/org to search when naming unknown repositories "
                               "(default: the namespaces this machine already works in)")
    converge.add_argument("--host", default="github.com",
                          help="host for --namespace values (default github.com)")
    converge.add_argument("--no-resolve", action="store_true",
                          help="do not contact any provider; report opaque ids only")
    converge.add_argument("--no-catalog", action="store_true",
                          help="do not record newly identified names locally")
    converge.set_defaults(handler=command_converge)

    handoff = subparsers.add_parser("handoff", help="reserved: handoff workflow")
    handoff.set_defaults(handler=lambda _args: _not_ready("handoff"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.handler is command_alias and args.repo_id and not args.name and not args.list:
        print("error: alias needs both a repo id and a name (or use --list)", file=sys.stderr)
        return 2
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
