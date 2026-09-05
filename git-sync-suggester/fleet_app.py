"""Foreground personal-fleet app: Tailscale reports, SQLite dashboard, paced replicas.

Run directly, or through sync_suggester.py fleet. No OS service, Git mutations, credential
configuration, or implicit cloud failover. The existing gh login is a hard prerequisite.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.gh_cli import GhError, run_gh
from config import default_config_dir
from fleet_events import NativeEvents
from fleet_net import FleetClient, local_identity, make_server
from fleet_observer import IncrementalObserver
from fleet_store import FleetStore, MAX_REPORT_BYTES
from folder_transport import FolderTransport, atomic_write_bytes
from manifest import fleet_id_for, is_fleet_secret, new_fleet_secret
from repo_transport import RepoTransport, create_state_repo
from watcher import semantic_fingerprint

APP_CONFIG = "fleet-app.json"


@contextmanager
def app_lock(directory):
    """One observer per local setup; OS releases the lock after crashes too."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "fleet-app.lock").open("a+b") as handle:
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("this fleet app is already running for this configuration") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, (json.dumps(value, indent=2) + "\n").encode())


def require_gh():
    # Capture output: gh status can include credential metadata. Never print or store it.
    proc = run_gh(["auth", "status"], check=False, timeout=30)
    if proc.returncode:
        raise ValueError("an existing working gh login is required; check 'gh auth status'")


def load_ui_assets():
    """Only named presentation assets are served; no source downloads or directory traversal."""
    files = {"/": ("fleet_dashboard.html", "text/html; charset=utf-8"),
             "/assets/fleet_standard.css": ("fleet_standard.css", "text/css; charset=utf-8"),
             "/assets/fleet_client.js": ("fleet_client.js", "text/javascript; charset=utf-8"),
             "/assets/fleet_view.js": ("fleet_view.js", "text/javascript; charset=utf-8"),
             "/assets/fleet_standard.js": ("fleet_standard.js", "text/javascript; charset=utf-8")}
    root = Path(__file__).resolve().parent
    return {url: ((root / name).read_bytes(), mime) for url, (name, mime) in files.items()}


class ReplicaSchedule:
    """Independent clocks. No cloud calls, including reads, before the next scheduled slot."""
    def __init__(self, entries, clock=time.monotonic):
        self.clock = clock
        now = clock()
        self.entries = [{"transport": t, "interval": seconds, "next": now + seconds,
                         "label": label} for t, seconds, label in entries]

    def tick(self, report, log=print):
        for entry in self.entries:
            now = self.clock()
            if now < entry["next"]:
                continue
            # A failed slot waits the full configured interval too, avoiding a retry storm.
            entry["next"] = now + entry["interval"]
            try:
                if isinstance(entry["transport"], RepoTransport):
                    health = entry["transport"].doctor()
                    if not health.get("private") or not health.get("permissions"):
                        raise ValueError("GitHub replica is no longer private and writable")
                entry["transport"].write_own_manifest(
                    report["manifest"]["machine_id"], report["manifest"], compress=True)
                log(f"scheduled {entry['label']} replica published")
            except (OSError, ValueError, GhError) as exc:
                log(f"scheduled {entry['label']} replica failed: {exc}")


def run_observer(config, config_dir, publish, stopping, once=False, event_source=None,
                 heartbeat=None):
    """Discover once, then refresh only repositories touched by native filesystem events."""
    entries = []
    if config.get("replica_folder"):
        entries.append((FolderTransport(config["replica_folder"]),
                        config["folder_seconds"], "folder"))
    if config.get("replica_repo"):
        entries.append((RepoTransport(config["replica_repo"]),
                        config["github_seconds"], "GitHub"))
    schedule = ReplicaSchedule(entries)
    observer = IncrementalObserver(config)
    started = time.monotonic()
    count = observer.inventory()
    print(f"Initial inventory found {count} repositories in {time.monotonic() - started:.1f}s. "
          "Native filesystem events now trigger targeted status checks; no periodic full scan. "
          "No source-repository fetches or writes. Ctrl-C stops the app.", flush=True)
    source = event_source or NativeEvents([Path(root) for root in config["roots"]])
    fingerprint, published_at = None, 0.0
    request_path = config_dir / "fleet-rescan.request"
    heartbeat = heartbeat or (lambda observed_at: None)

    def share(report, reason):
        nonlocal fingerprint, published_at
        raw = json.dumps(report).encode()
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("report exceeds the pilot size limit")
        atomic_write_bytes(config_dir / "fleet-latest.json", raw)
        try:
            publish(report)
            fingerprint = semantic_fingerprint(report["manifest"]) + json.dumps(
                [report["names"], report["issues"]], sort_keys=True)
            published_at = time.monotonic()
            print(f"Shared {len(report['manifest']['repositories'])} repos ({reason}).", flush=True)
        except (OSError, ValueError) as exc:
            print(f"Host unavailable; latest observation saved locally: {exc}", flush=True)

    try:
        report = observer.report()
        share(report, "initial inventory")
        if once:
            return
        while not stopping.is_set():
            try:
                changed = source.wait(timeout=1.0, debounce=config["debounce_seconds"])
                reason = None
                if request_path.exists():
                    request_path.unlink(missing_ok=True)
                    started = time.monotonic()
                    count = observer.inventory()
                    reason = f"manual inventory: {count} repos in {time.monotonic() - started:.1f}s"
                elif changed:
                    count = observer.refresh(changed)
                    if count:
                        reason = f"filesystem change: checked {count} repo(s)"

                now = time.monotonic()
                report = observer.report()
                current = semantic_fingerprint(report["manifest"]) + json.dumps(
                    [report["names"], report["issues"]], sort_keys=True)
                if reason and current != fingerprint:
                    share(report, reason)
                elif now - published_at >= config["heartbeat"]:
                    try:
                        heartbeat(report["manifest"]["observed_at"])
                        published_at = now
                    except (OSError, ValueError) as exc:
                        print(f"Host unavailable; heartbeat retained locally: {exc}", flush=True)
                schedule.tick(report)
            except (OSError, ValueError) as exc:
                print(f"Observation event failed; last report retained: {exc}", flush=True)
    finally:
        source.close()


def validate_app_config(config):
    if config.get("version") != 2 or config.get("mode") not in ("host", "connect"):
        raise ValueError("unsupported fleet app configuration")
    if not is_fleet_secret(config.get("fleet_secret")):
        raise ValueError("invalid fleet identity")
    if config.get("inventory_notice_acknowledged") is not True:
        raise ValueError("initial inventory discovery has not been acknowledged")
    if config.get("observation_mode") != "filesystem-events":
        raise ValueError("unsupported observation mode")
    if not config.get("roots") or any(not Path(p).is_dir() for p in config["roots"]):
        raise ValueError("every configured repository root must exist")
    for key in ("heartbeat", "folder_seconds", "github_seconds"):
        value = config.get(key)
        if type(value) is not int or value < 1:
            raise ValueError(f"{key} must be a positive number of seconds")
    debounce = config.get("debounce_seconds")
    if not isinstance(debounce, (int, float)) or isinstance(debounce, bool) or debounce < 0:
        raise ValueError("debounce_seconds must be zero or greater")
    if config["heartbeat"] > 60:
        raise ValueError("live heartbeat must be <= 60 seconds (stale threshold is 120 seconds)")
    if config["mode"] == "host" and not 1024 <= config.get("port", 0) <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    if config.get("replica_repo"):
        RepoTransport(config["replica_repo"])
    return config


def migrate_app_config(config):
    """Move the short-lived polling preview to native event observation."""
    if config.get("version") == 1:
        config = dict(config)
        config["version"] = 2
        config["inventory_notice_acknowledged"] = bool(
            config.pop("scan_notice_acknowledged", False))
        config["observation_mode"] = "filesystem-events"
        config["debounce_seconds"] = 0.75
        config.pop("interval", None)
    return config


def configure(args, directory, identity):
    path = directory / APP_CONFIG
    if path.exists():
        raise ValueError(f"configuration exists at {path}; use 'run' to resume, or edit it")
    if not args.root:
        raise ValueError("select your repository library with --root PATH (repeatable)")
    if not args.acknowledge_initial_scan:
        raise ValueError("setup performs one recursive inventory of every selected root. Review "
                         "the scope and pass --acknowledge-initial-scan, or use 'fleet setup'")
    config = {"version": 2, "mode": args.command,
              "roots": [str(Path(p).expanduser().resolve()) for p in args.root],
              "machine_id": identity["machine_id"], "label": args.label or identity["label"],
              "heartbeat": 30, "observation_mode": "filesystem-events",
              "debounce_seconds": args.debounce_seconds,
              "inventory_notice_acknowledged": True,
              "replica_folder": args.replica_folder, "folder_seconds": args.folder_seconds,
              "replica_repo": args.replica_repo, "github_seconds": args.github_seconds}
    if args.command == "host":
        config.update(fleet_secret=new_fleet_secret(), allowed_login=identity["login"], port=args.port)
    else:
        client = FleetClient(args.server)
        session = client.request("/v1/session")
        if session["machine_id"] != identity["machine_id"]:
            raise ValueError("host resolved a different device identity")
        config.update(fleet_secret=session["fleet_secret"], server=client.url)
    validate_app_config(config)
    if config.get("replica_repo"):
        # Explicit setup validation only; runtime repo I/O is strictly on its own schedule.
        health = RepoTransport(config["replica_repo"]).doctor()
        if not health.get("exists") and args.create_replica_repo:
            create_state_repo(config["replica_repo"])
            health = RepoTransport(config["replica_repo"]).doctor()
        if not health.get("exists") or not health.get("private") or not health.get("permissions"):
            raise ValueError("replica repo must already exist, be private, and be writable "
                             "by the active gh login; pass --create-replica-repo to create it")
    if config.get("replica_folder") and not Path(config["replica_folder"]).is_dir():
        raise ValueError("replica folder must already exist and be managed by your sync client")
    write_json(path, config)
    print(f"Saved setup: {path}. Resume with 'fleet run'.", flush=True)
    return config


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=default_config_dir())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="walk through live host/client setup and optional replica schedules")
    for name in ("host", "connect"):
        command = commands.add_parser(name, help="configure and start this foreground app")
        command.add_argument("--root", action="append", help="repository library, scanned recursively")
        command.add_argument("--label", help="display name; independent of stable device identity")
        command.add_argument("--debounce-seconds", type=float, default=0.75,
                             help="quiet time before a targeted status check (default 0.75)")
        command.add_argument("--acknowledge-initial-scan", action="store_true",
                             help="confirm one recursive inventory of every selected root")
        command.add_argument("--acknowledge-continuous-scan", action="store_true",
                             dest="acknowledge_initial_scan", help=argparse.SUPPRESS)
        command.add_argument("--replica-folder", help="optional folder already replicated by your sync client")
        command.add_argument("--folder-seconds", type=int, default=300)
        command.add_argument("--replica-repo", help="optional existing private owner/repo; any accessible org")
        command.add_argument("--create-replica-repo", action="store_true",
                             help="create --replica-repo privately after this explicit request")
        command.add_argument("--github-seconds", type=int, default=1800,
                             help="GitHub replica schedule, including reads; default 1800 seconds")
        if name == "host":
            command.add_argument("--port", type=int, default=8765)
        else:
            command.add_argument("--server", required=True, help="host's numeric Tailscale URL")
    commands.add_parser("run", help="resume the saved app; no service installation")
    commands.add_parser("doctor", help="show setup and connectivity without revealing secrets")
    commands.add_parser("rescan", help="request one deliberate local inventory refresh")
    replicas = commands.add_parser("replicas", help="configure optional folder/GitHub replicas while stopped")
    replicas.add_argument("--folder", help="existing directory managed by a folder-sync client")
    replicas.add_argument("--clear-folder", action="store_true")
    replicas.add_argument("--folder-seconds", type=int)
    replicas.add_argument("--repo", help="private writable GitHub owner/repo")
    replicas.add_argument("--create-repo", action="store_true",
                          help="create --repo privately after this explicit request")
    replicas.add_argument("--clear-repo", action="store_true")
    replicas.add_argument("--github-seconds", type=int)
    return parser


def setup_arguments(directory):
    """Interactive front door; the same validated configuration as the noninteractive flags."""
    print("Live fleet setup: keep one host app running and connect each observer to it.\n"
          "Uses the existing gh login and Tailscale account. No source files are uploaded.\n"
          "Repository names and status will be visible to your authorized fleet devices.")
    mode = input("Host the fleet here, or connect to an existing host? [connect]: ").strip() or "connect"
    if mode not in ("host", "connect"):
        raise ValueError("choose host or connect")
    arguments = ["--config-dir", str(directory), mode]
    if mode == "connect":
        arguments += ["--server", input("Host URL (http://TAILSCALE-IP:8765): ").strip()]
    root = input("Repository library folder (inventoried once, recursively): ").strip().strip('"')
    if not root:
        raise ValueError("a repository library folder is required")
    print(f"\nInitial inventory will recursively discover repositories under:\n  {root}\n"
          "Afterward native filesystem notifications inspect only a changed repository.\n"
          "There is no timed full scan. No source contents are copied or modified.")
    if input("Type SCAN to allow the initial inventory: ").strip() != "SCAN":
        raise ValueError("initial inventory was not acknowledged")
    arguments += ["--root", root, "--acknowledge-initial-scan"]
    folder = input("Optional already-synced folder for timed replicas [none]: ").strip().strip('"')
    if folder:
        arguments += ["--replica-folder", folder, "--folder-seconds",
                      input("Folder publication interval in seconds [300]: ").strip() or "300"]
    repo = input("Optional existing private GitHub state owner/repo [none]: ").strip()
    if repo:
        arguments += ["--replica-repo", repo]
        if input("Create it privately if it does not exist? [y/N]: ").strip().lower() == "y":
            arguments.append("--create-replica-repo")
        arguments += ["--github-seconds",
                      input("GitHub publication interval in seconds [1800]: ").strip() or "1800"]
    return build_parser().parse_args(arguments)


def _main(argv=None):
    args = build_parser().parse_args(argv)
    directory = args.config_dir.expanduser()
    try:
        if args.command == "rescan":
            if not (directory / APP_CONFIG).exists():
                raise ValueError("no saved fleet configuration")
            atomic_write_bytes(directory / "fleet-rescan.request", b"inventory requested\n")
            print("Requested one local inventory refresh. The running observer will perform it.")
            return 0
        require_gh()
        identity = local_identity()
        if args.command == "setup":
            args = setup_arguments(directory)
        if args.command == "replicas":
            path = directory / APP_CONFIG
            if not path.exists():
                raise ValueError("no saved fleet configuration")
            config = migrate_app_config(json.loads(path.read_text(encoding="utf-8")))
            if args.folder and args.clear_folder:
                raise ValueError("choose --folder or --clear-folder")
            if args.repo and args.clear_repo:
                raise ValueError("choose --repo or --clear-repo")
            if args.folder:
                folder = Path(args.folder).expanduser().resolve()
                if not folder.is_dir():
                    raise ValueError("--folder must already exist and be managed by a sync client")
                config["replica_folder"] = str(folder)
            elif args.clear_folder:
                config["replica_folder"] = None
            if args.folder_seconds is not None:
                config["folder_seconds"] = args.folder_seconds
            if args.repo:
                transport = RepoTransport(args.repo)
                health = transport.doctor()
                if not health.get("exists") and args.create_repo:
                    create_state_repo(args.repo)
                    health = transport.doctor()
                if not health.get("exists") or not health.get("private") or not health.get("permissions"):
                    raise ValueError("--repo must be private and writable; add --create-repo to create it")
                config["replica_repo"] = args.repo
            elif args.clear_repo:
                config["replica_repo"] = None
            if args.github_seconds is not None:
                config["github_seconds"] = args.github_seconds
            validate_app_config(config)
            write_json(path, config)
            print("Replica settings saved. Start the app with 'fleet run'.")
            return 0
        if args.command in ("host", "connect"):
            config = configure(args, directory, identity)
        else:
            path = directory / APP_CONFIG
            if not path.exists():
                raise ValueError("run 'fleet host --root PATH' or 'fleet connect --server URL --root PATH' first")
            saved = json.loads(path.read_text(encoding="utf-8"))
            config = validate_app_config(migrate_app_config(saved))
            if config != saved:
                write_json(path, config)
                print("Updated the saved observer from timed scans to filesystem events.", flush=True)
        if config["machine_id"] != identity["machine_id"]:
            raise ValueError("Tailscale device identity changed; review enrollment before rejoining")
        if args.command == "doctor":
            print(json.dumps({k: v for k, v in config.items() if k != "fleet_secret"}, indent=2))
            print("gh authenticated; Tailscale connected; fleet key set (hidden)")
            if config["mode"] == "connect":
                print(f"Host reports {len(FleetClient(config['server']).request('/v1/dashboard')['machines'])} machine(s)")
            return 0
        stopping = threading.Event()
        for name in ("SIGINT", "SIGTERM"):
            signal.signal(getattr(signal, name), lambda *_: stopping.set())
        server = None
        if config["mode"] == "host":
            if identity["login"] != config["allowed_login"]:
                raise ValueError("Tailscale user changed; host authorization needs review")
            store = FleetStore(directory / "fleet.sqlite3", fleet_id_for(config["fleet_secret"]))
            server = make_server((identity["ip"], config["port"]), store,
                                 config["fleet_secret"], config["allowed_login"], load_ui_assets(),
                                 display_settings={"observation_mode": config["observation_mode"],
                                                   "debounce_seconds": config["debounce_seconds"],
                                                   "root_count": len(config["roots"]),
                                                   "replica_folder": config.get("replica_folder"),
                                                   "folder_seconds": config.get("folder_seconds"),
                                                   "replica_repo": config.get("replica_repo"),
                                                   "github_seconds": config.get("github_seconds")})
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(f"Dashboard: http://{identity['ip']}:{config['port']}/", flush=True)
            print("Private Tailscale listener; only devices owned by the host's Tailscale user may join.", flush=True)
            publish = lambda report: store.put(config["machine_id"], report)
            heartbeat = lambda observed_at: store.touch(config["machine_id"], observed_at)
        else:
            client = FleetClient(config["server"])
            publish = lambda report: client.request("/v1/report", report)
            heartbeat = lambda observed_at: client.request(
                "/v1/heartbeat", {"observed_at": observed_at})
            print(f"Dashboard: {config['server']}/", flush=True)
        try:
            run_observer(config, directory, publish, stopping, heartbeat=heartbeat)
        finally:
            if server:
                server.shutdown()
                server.server_close()
        return 0
    except (OSError, ValueError, KeyError, GhError, EOFError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command in ("doctor", "rescan"):
        return _main(argv)
    try:
        with app_lock(args.config_dir.expanduser()):
            return _main(argv)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
