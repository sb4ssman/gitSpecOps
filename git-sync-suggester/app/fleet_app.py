"""Fleet app CLI. One kind of machine: a peer.

Every peer observes itself, publishes to whichever transports it has, serves its own dashboard
on loopback, and talks to other peers when Tailscale happens to be up. There is no host and no
client; see fleet_peer.py for why that matters and fleet_config.py for the schema.

`gh` is required only for the GitHub state-repo transport. Everything else — observation, a
synced folder, and the local dashboard — works without it.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
from _paths import bootstrap  # noqa: E402

bootstrap()  # core/, fleet/, app/ and the repo root (for shared/)

from shared.console import enable_unicode_output  # noqa: E402
from shared.gh_cli import GhError, run_gh  # noqa: E402
from config import default_config_dir, default_machine_id  # noqa: E402
from fleet_config import (APP_CONFIG, DEFAULT_FOLDER_SECONDS, DEFAULT_LOCAL_PORT,  # noqa: E402
                          DEFAULT_REPO_SECONDS, DEFAULT_TAILNET_PORT, describe, migrate,
                          new_config, validate)
from fleet_peer import run_peer  # noqa: E402
from folder_transport import atomic_write_bytes  # noqa: E402
from manifest import fleet_id_for, is_fleet_secret, new_fleet_secret  # noqa: E402
from repo_transport import RepoTransport, create_state_repo  # noqa: E402


@contextmanager
def app_lock(directory):
    """One peer per local configuration; the OS releases the lock after a crash too."""
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


def load_saved(directory: Path) -> dict:
    path = directory / APP_CONFIG
    if not path.exists():
        raise ValueError("no saved configuration; run 'fleet setup' first")
    saved = json.loads(path.read_text(encoding="utf-8"))
    config = validate(migrate(saved))
    if config != saved:
        write_json(path, config)
        print("Updated the saved configuration to the peer model (v3).", flush=True)
    return config


def require_gh():
    # Capture output: gh status can include credential metadata. Never print or store it.
    proc = run_gh(["auth", "status"], check=False, timeout=30)
    if proc.returncode:
        raise ValueError("a working gh login is required for the GitHub state repository; "
                         "check 'gh auth status'")


def resolve_machine_identity(want_tailnet: bool) -> tuple[str, str]:
    """A stable id for this peer, preferring Tailscale's node id when the tier is wanted.

    Falls back to the Sync Suggester machine id (hostname-derived, overridable) so that a peer
    can exist with Tailscale absent — which is the whole point of the peer model.
    """
    if want_tailnet:
        try:
            from fleet_net import local_identity

            identity = local_identity()
            return identity["machine_id"], identity["label"]
        except (OSError, ValueError) as exc:
            print(f"note: Tailscale is not usable right now ({exc}); this peer will use its "
                  "local machine id and enable the tailnet tier when Tailscale returns.",
                  flush=True)
    name = default_machine_id()
    return name, name


def configure(args, directory: Path) -> dict:
    path = directory / APP_CONFIG
    if path.exists():
        raise ValueError(f"configuration exists at {path}; use 'run' to resume, or edit it")
    if not args.root:
        raise ValueError("select your repository library with --root PATH (repeatable)")
    if not args.acknowledge_initial_scan:
        raise ValueError("setup performs one recursive inventory of every selected root. Review "
                         "the scope and pass --acknowledge-initial-scan, or use 'fleet setup'")
    transports = {}
    if args.folder:
        folder = Path(args.folder).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("--folder must already exist and be managed by your sync client")
        transports["folder"] = {"path": str(folder), "seconds": args.folder_seconds}
    if args.repo:
        require_gh()
        transport = RepoTransport(args.repo)
        health = transport.doctor()
        if not health.get("exists") and args.create_repo:
            create_state_repo(args.repo)
            health = transport.doctor()
        if not health.get("exists") or not health.get("private") or not health.get("permissions"):
            raise ValueError("--repo must exist, be private, and be writable by your gh login; "
                             "add --create-repo to create it")
        transports["repo"] = {"name": args.repo, "seconds": args.repo_seconds}
    if not args.no_tailnet:
        transports["tailnet"] = {"port": args.tailnet_port, "allowed_login": None}

    machine_id, label = resolve_machine_identity("tailnet" in transports)
    secret = args.fleet_secret or new_fleet_secret()
    if not is_fleet_secret(secret):
        raise ValueError("--fleet-secret must be 64 hexadecimal characters")
    config = new_config(machine_id, args.label or label, args.root, secret,
                        debounce_seconds=args.debounce_seconds, local_port=args.local_port,
                        transports=transports)
    validate(config)
    write_json(path, config)
    print(f"Saved: {path}\nTransports:\n{describe(config)}")
    if not args.fleet_secret:
        print(f"\nCreated fleet {fleet_id_for(secret)}. To add another machine, run setup there "
              f"with:\n\n    --fleet-secret {secret}\n\nCarry that value yourself. A peer on the "
              "tailnet can also hand it over automatically once you are connected.")
    return config


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config-dir", type=Path, default=default_config_dir())
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="guided first-run setup for this peer")
    setup.add_argument("--configure-only", action="store_true",
                       help="save the configuration and exit instead of starting")

    peer = commands.add_parser("peer", help="configure this peer non-interactively and start it")
    peer.add_argument("--root", action="append", help="repository library, inventoried once")
    peer.add_argument("--label", help="display name; independent of the stable machine id")
    peer.add_argument("--fleet-secret", help="join an existing fleet (64 hex characters)")
    peer.add_argument("--debounce-seconds", type=float, default=0.75)
    peer.add_argument("--acknowledge-initial-scan", action="store_true",
                      help="confirm one recursive inventory of every selected root")
    peer.add_argument("--acknowledge-continuous-scan", action="store_true",
                      dest="acknowledge_initial_scan", help=argparse.SUPPRESS)
    peer.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT,
                      help=f"loopback dashboard port (default {DEFAULT_LOCAL_PORT})")
    peer.add_argument("--folder", help="a directory your sync client already replicates")
    peer.add_argument("--folder-seconds", type=int, default=DEFAULT_FOLDER_SECONDS)
    peer.add_argument("--repo", help="a private GitHub owner/name to publish manifests into")
    peer.add_argument("--create-repo", action="store_true",
                      help="create --repo privately after this explicit request")
    peer.add_argument("--repo-seconds", type=int, default=DEFAULT_REPO_SECONDS)
    peer.add_argument("--no-tailnet", action="store_true",
                      help="do not talk to peers over Tailscale")
    peer.add_argument("--tailnet-port", type=int, default=DEFAULT_TAILNET_PORT)
    peer.add_argument("--configure-only", action="store_true")

    commands.add_parser("run", help="resume this peer; installs no service")
    commands.add_parser("tray", help="resume behind a tray icon (falls back to 'run')")
    commands.add_parser("doctor", help="show configuration and reachability; hides the secret")
    commands.add_parser("rescan", help="request one deliberate local inventory refresh")

    autostart = commands.add_parser("autostart", help="inspect or change start-at-login")
    autostart.add_argument("action", choices=("status", "enable", "disable"), nargs="?",
                           default="status")
    autostart.add_argument("--systemd", action="store_true",
                           help="Linux: use a systemd --user unit instead of an autostart entry")

    transports = commands.add_parser("transports", help="add or remove transports while stopped")
    transports.add_argument("--folder")
    transports.add_argument("--clear-folder", action="store_true")
    transports.add_argument("--folder-seconds", type=int)
    transports.add_argument("--repo")
    transports.add_argument("--create-repo", action="store_true")
    transports.add_argument("--clear-repo", action="store_true")
    transports.add_argument("--repo-seconds", type=int)
    transports.add_argument("--tailnet", action="store_true", help="enable the tailnet tier")
    transports.add_argument("--clear-tailnet", action="store_true")
    transports.add_argument("--tailnet-port", type=int)
    return parser


def setup_arguments(directory: Path, configure_only=False):
    """Interactive first run. Offers every transport; requires none."""
    print("Fleet setup. Every machine is a peer: it watches its own repositories, publishes\n"
          "what it sees, and shows you a dashboard. Nothing here needs another machine to be\n"
          "running, and no machine is in charge of any other.\n")
    arguments = ["--config-dir", str(directory), "peer"]
    root = input("Repository library folder (inventoried once, recursively): ").strip().strip('"')
    if not root:
        raise ValueError("a repository library folder is required")
    print(f"\nOne recursive inventory will run over:\n  {root}\n"
          "After that, filesystem notifications inspect only a repository that changed.\n"
          "No source content is copied, sent, or modified.")
    if input("Type SCAN to allow the initial inventory: ").strip() != "SCAN":
        raise ValueError("initial inventory was not acknowledged")
    arguments += ["--root", root, "--acknowledge-initial-scan"]

    print("\nHow should this machine share status with your others?\n"
          "These are complements — set up as many as you can. Press Enter to skip any.")
    secret = input("Fleet key from a machine you already set up [new fleet]: ").strip()
    if secret:
        arguments += ["--fleet-secret", secret]
    folder = input("A folder your sync client already replicates [none]: ").strip().strip('"')
    if folder:
        arguments += ["--folder", folder]
    repo = input("A private GitHub repo for durable status, owner/name [none]: ").strip()
    if repo:
        arguments += ["--repo", repo]
        if input("Create it privately if it does not exist? [y/N]: ").strip().lower() == "y":
            arguments.append("--create-repo")
    if input("Talk directly to your other machines over Tailscale? [Y/n]: ").strip().lower() \
            in ("n", "no"):
        arguments.append("--no-tailnet")
    if configure_only:
        arguments.append("--configure-only")
    return build_parser().parse_args(arguments)


def command_transports(args, directory: Path) -> int:
    config = load_saved(directory)
    transports = dict(config.get("transports") or {})
    if args.folder and args.clear_folder:
        raise ValueError("choose --folder or --clear-folder")
    if args.repo and args.clear_repo:
        raise ValueError("choose --repo or --clear-repo")
    if args.folder:
        folder = Path(args.folder).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("--folder must already exist")
        transports["folder"] = {"path": str(folder),
                                "seconds": args.folder_seconds or DEFAULT_FOLDER_SECONDS}
    elif args.clear_folder:
        transports.pop("folder", None)
    elif args.folder_seconds and transports.get("folder"):
        transports["folder"]["seconds"] = args.folder_seconds
    if args.repo:
        require_gh()
        transport = RepoTransport(args.repo)
        health = transport.doctor()
        if not health.get("exists") and args.create_repo:
            create_state_repo(args.repo)
            health = transport.doctor()
        if not health.get("exists") or not health.get("private") or not health.get("permissions"):
            raise ValueError("--repo must be private and writable; add --create-repo to create it")
        transports["repo"] = {"name": args.repo,
                              "seconds": args.repo_seconds or DEFAULT_REPO_SECONDS}
    elif args.clear_repo:
        transports.pop("repo", None)
    elif args.repo_seconds and transports.get("repo"):
        transports["repo"]["seconds"] = args.repo_seconds
    if args.tailnet:
        transports["tailnet"] = {"port": args.tailnet_port or DEFAULT_TAILNET_PORT,
                                 "allowed_login": None}
    elif args.clear_tailnet:
        transports.pop("tailnet", None)
    elif args.tailnet_port and transports.get("tailnet"):
        transports["tailnet"]["port"] = args.tailnet_port
    config["transports"] = transports
    validate(config)
    write_json(directory / APP_CONFIG, config)
    print(f"Transports now:\n{describe(config)}\nStart with 'fleet run'.")
    return 0


def command_doctor(config: dict) -> int:
    shown = {k: v for k, v in config.items() if k != "fleet_secret"}
    print(json.dumps(shown, indent=2))
    print(f"\nfleet id: {fleet_id_for(config['fleet_secret'])}  (key is set and hidden)")
    print(f"dashboard: http://127.0.0.1:{config['local_port']}/  — local, always available")
    if (config.get("transports") or {}).get("tailnet"):
        try:
            from fleet_net import discover_hosts

            port = config["transports"]["tailnet"]["port"]
            peers = discover_hosts(port=port, timeout=0.6)
            for peer in peers:
                state = "answering" if peer["serving"] else (
                    "online, not running the app" if peer["online"] else "offline")
                print(f"  peer {peer['label']:<20} {state}")
            if not peers:
                print("  no tailnet peers found")
        except (OSError, ValueError) as exc:
            print(f"  tailnet unavailable: {exc}")
    return 0


def run_autostart(args) -> int:
    import fleet_autostart

    enable_unicode_output()
    inner = ["--config-dir", str(args.config_dir.expanduser()), "tray"]
    if args.systemd and sys.platform.startswith("linux"):
        if args.action == "enable":
            target = fleet_autostart.systemd_enable(
                fleet_autostart.launch_command(inner, script=__file__))
            print(f"Start at login enabled via systemd --user: {target}\n"
                  "Without 'loginctl enable-linger' this runs only while you are logged in.")
        elif args.action == "disable":
            print(f"Removed: {fleet_autostart.systemd_disable()}")
        else:
            print(json.dumps({"method": "systemd --user",
                              "enabled": fleet_autostart._systemd_unit_path().is_file()},
                             indent=2))
        return 0
    if args.action == "enable":
        print(json.dumps(fleet_autostart.enable(inner, script=__file__), indent=2))
    elif args.action == "disable":
        print(json.dumps(fleet_autostart.disable(), indent=2))
    else:
        print(json.dumps(fleet_autostart.status(), indent=2))
    return 0


def _main(argv=None, stopping=None, on_ready=None):
    """`stopping`/`on_ready` are the shell seam used by fleet_tray.py.

    A caller supplying `stopping` owns the lifecycle and may not be on the main thread, so
    signal handlers are registered only for a plain foreground run — `signal.signal` raises
    off the main thread.
    """
    enable_unicode_output()
    args = build_parser().parse_args(argv)
    directory = args.config_dir.expanduser()
    try:
        if args.command == "rescan":
            if not (directory / APP_CONFIG).exists():
                raise ValueError("no saved fleet configuration")
            atomic_write_bytes(directory / "fleet-rescan.request", b"inventory requested\n")
            print("Requested one local inventory refresh; the running peer will perform it.")
            return 0
        if args.command == "transports":
            return command_transports(args, directory)
        if args.command == "setup":
            args = setup_arguments(directory, args.configure_only)
        if args.command == "peer":
            config = configure(args, directory)
            if args.configure_only:
                return 0
        else:
            config = load_saved(directory)
        if args.command == "doctor":
            return command_doctor(config)

        if stopping is None:
            stopping = threading.Event()
            for name in ("SIGINT", "SIGTERM"):
                signal.signal(getattr(signal, name), lambda *_: stopping.set())
        return run_peer(config, directory, stopping, on_ready=on_ready)
    except (OSError, ValueError, KeyError, GhError, EOFError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


RETIRED = {"host", "connect"}


def main(argv=None, stopping=None, on_ready=None):
    enable_unicode_output()  # before argparse, which may print and exit on --help
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(token in RETIRED for token in argv):
        print("error: 'host' and 'connect' are gone — every machine is now a peer.\n"
              "  first run : fleet setup\n"
              "  scripted  : fleet peer --root PATH --acknowledge-initial-scan\n"
              "An existing host or client configuration migrates automatically on 'fleet run'.",
              file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    if args.command == "autostart":
        try:
            return run_autostart(args)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.command == "tray":
        from fleet_tray import TrayUnavailable, run_tray

        inner = ["--config-dir", str(args.config_dir.expanduser()), "run"]
        try:
            return run_tray(inner)
        except TrayUnavailable as exc:
            print(f"note: {exc}; running in the foreground instead", flush=True)
            return main(inner, stopping, on_ready)
    if args.command in ("doctor", "rescan"):
        return _main(argv, stopping, on_ready)
    try:
        with app_lock(args.config_dir.expanduser()):
            return _main(argv, stopping, on_ready)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
