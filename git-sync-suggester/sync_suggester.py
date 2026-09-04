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
from aggregate import build_rows, load_manifests, machine_views, render_dashboard
from config import (
    default_config,
    default_config_dir,
    load_catalog,
    load_config,
    merge_catalog,
    roots_from_archive_registry,
    save_catalog,
    save_config,
    validate_config,
)
from folder_transport import FolderTransport
from manifest import build_manifest
from observer import RootSpec, observe_roots
from watcher import DEFAULT_HEARTBEAT_SECONDS, DEFAULT_INTERVAL_SECONDS, run_watch

REPO_ROOT = Path(__file__).resolve().parent.parent
PREVIEW_MACHINE_ID = "local-preview"


def _config_dir(args: argparse.Namespace) -> Path:
    return Path(args.config_dir).expanduser() if args.config_dir else default_config_dir()


def _not_ready(command: str) -> int:
    print(f"'{command}' is not implemented yet; it moves work between machines and needs its "
          "own design pass. Use 'check', 'watch', 'dashboard', 'alias', or 'doctor'.")
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

    config = default_config(args.machine_id)
    if args.machine_label:
        config["machine_label"] = args.machine_label
    if args.state_dir:
        config["state_dir"] = str(Path(args.state_dir).expanduser())
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
    print(json.dumps(config, indent=2, sort_keys=True))
    return 0


class Resolution:
    """What `check` and `watch` both need: where to look, who we are, where to publish."""

    def __init__(self, config_dir: Path, config: dict | None, specs: list[RootSpec],
                 source: str, machine_id: str, machine_label: str, state_dir: str | None):
        self.config_dir, self.config = config_dir, config
        self.specs, self.source = specs, source
        self.machine_id, self.machine_label = machine_id, machine_label
        self.state_dir = state_dir


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
    state_dir = args.state_dir or (config or {}).get("state_dir")
    machine_id = args.machine_id or (config or {}).get("machine_id") or PREVIEW_MACHINE_ID
    # An explicit --machine-id with no label should label itself, not inherit the saved label.
    machine_label = (args.machine_label
                     or (None if args.machine_id else (config or {}).get("machine_label"))
                     or machine_id)
    if state_dir and machine_id == PREVIEW_MACHINE_ID:
        print("error: publishing needs a real machine id — run 'init' or pass --machine-id",
              file=sys.stderr)
        return 2
    return Resolution(config_dir, config, specs, source, machine_id, machine_label, state_dir)


def command_check(args: argparse.Namespace) -> int:
    resolved = _resolve(args)
    if isinstance(resolved, int):
        return resolved
    config_dir, config = resolved.config_dir, resolved.config
    specs, source = resolved.specs, resolved.source
    state_dir, machine_id, machine_label = (resolved.state_dir, resolved.machine_id,
                                            resolved.machine_label)

    observation = observe_roots(specs)
    manifest = build_manifest(machine_id, machine_label, observation.repositories)

    catalog = load_catalog(config_dir)
    merged = merge_catalog(catalog, observation.catalog)
    if config and not args.no_catalog:
        save_catalog(config_dir, merged)

    published = None
    if state_dir and not args.no_publish:
        published = FolderTransport(state_dir).write_own_manifest(machine_id, manifest)

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    elif state_dir and not args.local_only:
        print(_dashboard_text(state_dir, config, merged, own=manifest, show_all=args.all))
    else:
        print(render_table(manifest, merged))

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
    if not resolved.state_dir:
        print("error: watch publishes, so it needs a state directory. "
              "Run 'init --state-dir PATH' or pass --state-dir.", file=sys.stderr)
        return 2
    transport = FolderTransport(resolved.state_dir)
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
        observation = observe_roots(resolved.specs)
        if resolved.config and not args.no_catalog:
            save_catalog(resolved.config_dir,
                         merge_catalog(load_catalog(resolved.config_dir), observation.catalog))
        return build_manifest(resolved.machine_id, resolved.machine_label,
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


def _dashboard_text(state_dir: str, config: dict | None, catalog: dict[str, dict],
                    own: dict | None = None, show_all: bool = False) -> str:
    transport = FolderTransport(state_dir)
    manifests, issues = load_manifests(transport)
    if own is not None:
        manifests = [m for m in manifests if m.get("machine_id") != own["machine_id"]] + [own]
    stale_hours = (config or {}).get("stale_hours", 24)
    expired_days = (config or {}).get("expired_days", 7)
    now = datetime.now(timezone.utc)
    views = sorted(machine_views(manifests, now, stale_hours, expired_days),
                   key=lambda view: (own is None or view.machine_id != own["machine_id"],
                                     view.label.lower()))
    text = render_dashboard(views, build_rows(views, catalog), now, show_all=show_all)
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
    state_dir = args.state_dir or (config or {}).get("state_dir")
    if not state_dir:
        print("error: no state directory. Run 'init --state-dir PATH' or pass --state-dir.",
              file=sys.stderr)
        return 2
    print(_dashboard_text(state_dir, config, load_catalog(config_dir), show_all=args.all))
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


def command_doctor(args: argparse.Namespace) -> int:
    config_dir = _config_dir(args)
    report: dict = {"config_dir": str(config_dir)}
    try:
        config = load_config(config_dir)
        report["config"] = config
        report["config_error"] = None
    except ValueError as exc:
        config, report["config"], report["config_error"] = None, None, str(exc)
    report["catalog_entries"] = len(load_catalog(config_dir))
    state_dir = args.state_dir or (config or {}).get("state_dir")
    report["state_dir"] = state_dir
    if state_dir:
        transport = FolderTransport(state_dir)
        report["transport"] = transport.doctor()
        manifests, issues = load_manifests(transport)
        report["machines"] = sorted(m["machine_id"] for m in manifests)
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
    init.add_argument("--machine-label", help="readable label (default: the machine id)")
    init.add_argument("--root", action="append", help="root scanned by direct children (repeatable)")
    init.add_argument("--recursive-root", action="append",
                      help="root scanned recursively (repeatable)")
    init.add_argument("--state-dir", help="folder your sync client replicates between machines")
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
    check.add_argument("--local-only", action="store_true", help="skip peers; show this machine only")
    check.add_argument("--all", action="store_true", help="list every repository, not just exceptions")
    check.add_argument("--no-publish", action="store_true", help="observe without writing a manifest")
    check.add_argument("--no-catalog", action="store_true", help="do not update the local catalog")
    check.add_argument("--json", action="store_true", help="print the privacy-minimized manifest")
    check.set_defaults(handler=command_check)

    dashboard = subparsers.add_parser("dashboard", help="read peer manifests without observing")
    dashboard.add_argument("--state-dir", help="override the saved manifest folder")
    dashboard.add_argument("--all", action="store_true", help="list every repository, not just exceptions")
    dashboard.set_defaults(handler=command_dashboard)

    alias = subparsers.add_parser("alias", help="name a repository in the local-only catalog")
    alias.add_argument("repo_id", nargs="?", help="repo id or unique prefix")
    alias.add_argument("name", nargs="?", help="readable name to show for it")
    alias.add_argument("--list", action="store_true", help="list catalog entries")
    alias.set_defaults(handler=command_alias)

    doctor = subparsers.add_parser("doctor", help="inspect local state and transport, changing nothing")
    doctor.add_argument("--state-dir", help="override the saved manifest folder")
    doctor.set_defaults(handler=command_doctor)

    watch = subparsers.add_parser("watch", help="keep observing and republish when facts change")
    watch.add_argument("--root", action="append", help="root to inspect (overrides saved roots)")
    watch.add_argument("--recursive-root", action="append", help="recursive root (overrides saved)")
    watch.add_argument("--recursive", action="store_true", help="scan every --root recursively")
    watch.add_argument("--machine-id", help="override the saved machine id")
    watch.add_argument("--machine-label", help="override the saved readable label")
    watch.add_argument("--state-dir", help="override the saved manifest folder")
    watch.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS,
                       help=f"seconds between observations (default {DEFAULT_INTERVAL_SECONDS})")
    watch.add_argument("--heartbeat", type=float, default=DEFAULT_HEARTBEAT_SECONDS,
                       help="seconds before republishing unchanged facts "
                            f"(default {DEFAULT_HEARTBEAT_SECONDS})")
    watch.add_argument("--once", action="store_true", help="run a single cycle and exit")
    watch.add_argument("--cycles", type=int, help="stop after this many cycles")
    watch.add_argument("--no-catalog", action="store_true", help="do not update the local catalog")
    watch.set_defaults(handler=command_watch)

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
