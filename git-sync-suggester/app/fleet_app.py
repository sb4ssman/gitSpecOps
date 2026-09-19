"""Fleet app CLI. One kind of machine: a peer.

Every peer observes itself, publishes to whichever transports it has, serves its own dashboard
on loopback, and talks to other peers when Tailscale happens to be up. There is no host and no
client; see fleet_peer.py for why that matters and fleet_config.py for the schema.

`gh` is required only for the GitHub state-repo transport. Everything else — observation, a
synced folder, and the local dashboard — works without it.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import signal
import shutil
import socket
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
                          new_config, policy_record, recovery_policy, validate)
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
        print("Updated the saved configuration to the current format.", flush=True)
    return config


def offer_start_at_login(inner: list[str]) -> None:
    """Ask once at the end of setup. Declining is fine; the tray menu can turn it on later."""
    try:
        answer = input("Start gitSpecOps automatically when you log in? [Y/n]: ").strip().lower()
    except EOFError:
        return
    if answer in ("n", "no"):
        print("Start at login left off. Turn it on later from the tray menu, or run "
              "'fleet autostart enable'.")
        return
    import fleet_autostart

    try:
        result = fleet_autostart.enable(inner, script=__file__)
        print(f"Start at login enabled ({result['method']}).")
    except (OSError, ValueError) as exc:
        print(f"Could not enable start at login: {exc}")


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
              f"with:\n\n    --fleet-secret {secret}\n\nCarry that value yourself. The tailnet "
              "session endpoint exists, but automatic key exchange is not wired into setup yet.")
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
    commands.add_parser("preflight", help="check setup prerequisites and optional tiers without changing anything")
    commands.add_parser("rescan", help="request one deliberate local inventory refresh")
    catchup = commands.add_parser("catchup",
        help="fresh-fetch observed repositories and preview safe fast-forward pulls")
    catchup.add_argument("--apply", action="store_true",
                         help="apply only clean, behind-only fast-forward pulls")
    catchup.add_argument("--yes", action="store_true",
                         help="confirm --apply non-interactively; required with --apply")
    commands.add_parser("safe-to-wipe",
                        help="fresh-fetch every observed checkout and report whether this machine is replaceable")
    audit = commands.add_parser("audit", help="read-only audit of local remotes and unfinished work")
    audit.add_argument("--json", action="store_true", help="emit machine-readable local audit rows")
    materialize = commands.add_parser("materialize", help="clone this machine's observed working set into a new library")
    materialize.add_argument("--destination", type=Path, required=True, help="existing library folder to fill")
    materialize.add_argument("--apply", action="store_true", help="clone planned missing repositories")
    materialize.add_argument("--yes", action="store_true", help="confirm --apply")
    buffers = commands.add_parser("live-buffers", help="explicitly inspect local VS Code unsaved-buffer metadata")
    buffers.add_argument("--backup-root", type=Path,
                         help="existing VS Code Backups folder (default on Windows)")
    client = commands.add_parser("git-client", help="configure an optional local desktop Git client")
    client.add_argument("--client", choices=("sourcetree", "github-desktop"))
    client.add_argument("--executable", type=Path, help="installed client executable at a custom location")
    client.add_argument("--disable", action="store_true")

    basket = commands.add_parser("baskets",
        help="choose which namespaces this machine observes and publishes")
    basket.add_argument("--scope", choices=("observe", "publish", "capture"),
                        help="which scope to change; omit to print the current baskets")
    basket.add_argument("--mode", choices=("all", "none", "only", "except"))
    basket.add_argument("--namespace", action="append", metavar="HOST/OWNER",
                        help="repeatable; required for --mode only/except")

    recovery = commands.add_parser("recovery", help="configure and inspect unfinished-work snapshots")
    recovery.add_argument("action", choices=("configure", "status", "policy", "capture",
                                                "preview", "restore", "acknowledge", "retire"))
    recovery.add_argument("--location", type=Path,
                          help="separate existing sync folder for recovery snapshots")
    recovery.add_argument("--confirm-private-location", action="store_true",
                          help="confirm this location is appropriate for source content")
    recovery.add_argument("--repo", type=Path, help="one observed checkout to capture")
    recovery.add_argument("--untracked", action="append", default=[], metavar="PATH",
                          help="explicit repository-relative untracked file to carry (repeatable)")
    recovery.add_argument("--obey-gitignore", choices=("on", "off"),
                          help="local policy setting for --repo")
    recovery.add_argument("--secret-protection", choices=("on", "off"),
                          help="local policy setting for --repo")
    recovery.add_argument("--allow-path", action="append", default=None, metavar="PATH",
                          help="replace the local allowed-path list for --repo (repeatable)")
    recovery.add_argument("--clear-allow-paths", action="store_true",
                          help="clear the local allowed-path list for --repo")
    recovery.add_argument("--confirm-relaxed-policy", action="store_true",
                          help="confirm a policy that weakens capture's default protections")
    recovery.add_argument("--source", help="source machine id when acknowledging a peer snapshot")
    recovery.add_argument("--repo-id", help="opaque repository id when acknowledging a peer snapshot")
    recovery.add_argument("--version", help="snapshot version when acknowledging a peer snapshot")
    recovery.add_argument("--source-repo", type=Path,
                          help="local repository holding a snapshot base, for disposable restore")
    recovery.add_argument("--destination", type=Path,
                          help="new or empty disposable checkout destination, for restore")
    recovery.add_argument("--yes", action="store_true",
                          help="confirm a source-content copy or acknowledgement")

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


def guided_durable_arguments() -> list[str]:
    """Prepare an explicit repo choice; creation happens only in configure()."""
    if input("Set up durable status in a private GitHub repository? [y/N]: ").strip().lower() \
            not in ("y", "yes"):
        return []
    require_gh()
    suggestion = ""
    try:
        login = run_gh(["api", "user", "--jq", ".login"], timeout=30).stdout.strip()
        candidate = f"{login}/gitspecops-fleet-state"
        RepoTransport(candidate)  # validate before presenting CLI output as a name
        suggestion = candidate
    except (GhError, OSError, ValueError):
        print("Could not suggest an owner; enter an accessible owner/name below.")
    print("\nUse a dedicated private repository that gitSpecOps manages. The app creates or\n"
          "replaces its machine status files under machines/ using your existing gh login.\n"
          "It publishes initial status when started, then changes at most once every "
          f"{DEFAULT_REPO_SECONDS // 60} minutes.\n"
          "Changes waiting for that interval are kept for later delivery while the app runs;\n"
          "failed writes retry after the interval. Stopping the app can leave changes unsent.\n"
          "This stores status only: no source files, repository history, or recovery snapshots.\n"
          "Repository and branch identities in those status files are salted digests.\n"
          "You can inspect the repository; gitSpecOps never clones it.\n")
    prompt = f"State repository [{suggestion}]: " if suggestion else "State repository owner/name: "
    spec = input(prompt).strip() or suggestion
    if not spec:
        print("Durable status skipped.")
        return []
    health = RepoTransport(spec).doctor()
    if health.get("exists"):
        if not health.get("private") or not health.get("permissions"):
            raise ValueError("the state repository must be private and writable")
        confirmation = f"USE {spec}"
        action = "allow gitSpecOps to manage its status files there"
        extra = []
    else:
        confirmation = f"CREATE {spec}"
        action = "create this private repository for gitSpecOps"
        extra = ["--create-repo"]
    if input(f"Type {confirmation} to {action} [Enter skips]: ").strip() != confirmation:
        print("Durable status skipped; no repository will be created or used.")
        return []
    return ["--repo", spec, *extra]


def guided_tailnet_join_secret() -> str:
    """Offer a deliberate, authenticated key hand-off from a running peer.

    The endpoint is reachable only over the tailnet and authorizes the caller with Tailscale's
    identity check.  It is still opt-in: a wrong or unavailable peer must fall back to the
    manual key rather than making setup look as though it joined a fleet when it did not.
    """
    if input("Join a running peer over Tailscale instead of pasting a fleet key? [y/N]: ").strip().lower() \
            not in ("y", "yes"):
        return ""
    try:
        from fleet_net import FleetClient, discover_hosts

        hosts = [item for item in discover_hosts() if item.get("serving")]
        if not hosts:
            print("No running fleet peer was found. Paste a fleet key instead, or start one peer first.")
            return ""
        for index, host in enumerate(hosts, start=1):
            print(f"  {index}. {host['label']}")
        answer = input("Peer number [Enter cancels]: ").strip()
        if not answer:
            return ""
        host = hosts[int(answer) - 1]
        session = FleetClient(host["url"]).request("/v1/session")
        secret = session.get("fleet_secret") if isinstance(session, dict) else None
        if not is_fleet_secret(secret):
            raise ValueError("peer returned no valid fleet key")
        print(f"Joined fleet {fleet_id_for(secret)} through authenticated peer {host['label']}.")
        return secret
    except (IndexError, OSError, ValueError) as exc:
        print(f"Could not join a peer ({exc}). Paste a fleet key instead.")
        return ""


def setup_arguments(directory: Path, configure_only=False):
    """Interactive first run. Offers every transport; requires none."""
    print("Fleet setup. Every machine is a peer: it watches its own repositories, publishes\n"
          "what it sees, and shows you a dashboard. Nothing here needs another machine to be\n"
          "running, and no machine is in charge of any other.\n")
    readiness = preflight_state()
    print(render_preflight(readiness))
    if not readiness["git"]:
        raise ValueError("Git is required before fleet setup can observe a repository library")
    if not readiness["dashboard"]:
        raise ValueError("the default dashboard port is unavailable; use non-interactive 'fleet peer' with --local-port")
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
    if not secret and readiness["tailnet"]:
        secret = guided_tailnet_join_secret()
    if secret:
        arguments += ["--fleet-secret", secret]
    if readiness["github"]:
        arguments += guided_durable_arguments()
    else:
        print("GitHub durable status skipped: gh is unavailable or not logged in.")
    suggested = readiness["folders"][0] if readiness["folders"] else ""
    folder = (input(f"A folder your sync client already replicates [{suggested or 'none'}]: ")
              .strip().strip('"') or suggested)
    if folder:
        arguments += ["--folder", folder]
    if not readiness["tailnet"]:
        print("Tailscale live sharing skipped: it is not connected. Add it later with 'fleet transports --tailnet'.")
        arguments.append("--no-tailnet")
    elif input("Talk directly to your other machines over Tailscale? [Y/n]: ").strip().lower() \
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


def command_baskets(args, directory: Path) -> int:
    """Print or change one scope. Capture remains off until recovery setup is confirmed."""
    import baskets

    config = load_saved(directory)
    scopes = config.get("baskets") or copy.deepcopy(baskets.DEFAULT_SCOPES)
    if not args.scope:
        print(f"Baskets on this machine:\n{baskets.describe(scopes)}\n\n"
              "Namespaces are host/owner, e.g. github.com/your-org. Observing and publishing are\n"
              "separate: narrowing 'publish' keeps a repository visible here while hiding its\n"
              "state from every other machine.")
        config["baskets"] = scopes
        return 0
    if not args.mode:
        raise ValueError("--scope needs --mode")
    selection = baskets.parse_selection(args.mode, args.namespace)
    scopes = {**scopes, args.scope: selection}
    config["baskets"] = baskets.validate_scopes(scopes)
    validate(config)
    write_json(directory / APP_CONFIG, config)
    print(f"Baskets now:\n{baskets.describe(scopes)}")
    if args.scope == "observe":
        print("\nRun 'fleet rescan' (or restart the peer) to apply this to the inventory.")
    elif args.scope == "capture":
        print("\nCapture selection is local-only. With a separately confirmed recovery location, "
              "the running peer captures selected repositories after filesystem quiet periods.")
    else:
        print("\nWithheld repositories stay on your local dashboard and are published to nothing.")
    return 0


def command_recovery(args, directory: Path) -> int:
    """Configure the content tier separately from names-free status transports."""
    from snapshot_store import SnapshotStore, StoreRefused, validate_location

    config = load_saved(directory)
    recovery = dict(config["recovery"])
    if args.action == "configure":
        if args.location is None:
            raise ValueError("recovery configure needs --location PATH")
        status_folder = ((config.get("transports") or {}).get("folder") or {}).get("path")
        try:
            warnings = validate_location(args.location, status_folder=status_folder,
                                         roots=[Path(root) for root in config["roots"]])
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
        if warnings and not args.confirm_private_location:
            raise ValueError("recovery location needs --confirm-private-location after review: "
                             + " ".join(warnings))
        recovery["location"] = str(args.location.expanduser().resolve())
        recovery["confirmed"] = True
        config["recovery"] = recovery
        validate(config)
        write_json(directory / APP_CONFIG, config)
        print("Recovery location saved. It is separate from status publication; configuring it "
              "does not capture any file.\n" + "\n".join(f"warning: {item}" for item in warnings))
        return 0
    location = recovery["location"]
    if location is None:
        print("Recovery is not configured. Use 'fleet recovery configure --location PATH "
              "--confirm-private-location'.")
        return 0
    store = SnapshotStore(location, config["machine_id"])
    if args.action == "policy":
        if args.repo is None:
            raise ValueError("recovery policy needs --repo PATH")
        from fleet_observer import IncrementalObserver

        observer = IncrementalObserver(config)
        observer.inventory()
        wanted = args.repo.expanduser().resolve()
        repo_id = next((identity for identity, path in observer.local_repositories().items()
                        if path == wanted), None)
        if repo_id is None:
            raise ValueError("that checkout is not in this machine's observed inventory")
        current = recovery_policy(config, repo_id)
        changed = any((args.obey_gitignore, args.secret_protection,
                       args.allow_path is not None, args.clear_allow_paths))
        if not changed:
            print(json.dumps({"repo_id": repo_id, **policy_record(current)}, indent=2))
            return 0
        if args.allow_path is not None and args.clear_allow_paths:
            raise ValueError("choose --allow-path or --clear-allow-paths")
        updated = type(current)(
            obey_gitignore=(args.obey_gitignore == "on" if args.obey_gitignore else current.obey_gitignore),
            secret_protection=(args.secret_protection == "on" if args.secret_protection
                               else current.secret_protection),
            allow_paths=(tuple(args.allow_path) if args.allow_path is not None else
                         (() if args.clear_allow_paths else current.allow_paths)))
        relaxed = (not updated.obey_gitignore or not updated.secret_protection
                   or bool(updated.allow_paths))
        if relaxed and not args.confirm_relaxed_policy:
            raise ValueError("this policy weakens default capture protection; review and re-run "
                             "with --confirm-relaxed-policy")
        recovery["policies"] = {**recovery["policies"], repo_id: policy_record(updated)}
        config["recovery"] = recovery
        validate(config)
        write_json(directory / APP_CONFIG, config)
        print("Saved local-only recovery policy:\n" + json.dumps(
            {"repo_id": repo_id, **policy_record(updated)}, indent=2))
        return 0
    if args.action == "capture":
        if not args.yes:
            raise ValueError("recovery capture copies saved source content; review and re-run with --yes")
        if args.repo is None:
            raise ValueError("recovery capture needs --repo PATH")
        from capture import CaptureRefused, capture
        from fleet_observer import IncrementalObserver

        observer = IncrementalObserver(config)
        observer.inventory()
        wanted = args.repo.expanduser().resolve()
        paths = observer.local_repositories()
        repo_id = next((identity for identity, path in paths.items() if path == wanted), None)
        if repo_id is None:
            raise ValueError("that checkout is not in this machine's observed inventory")
        namespace = observer.namespaces().get(repo_id)
        import baskets
        if not namespace or not baskets.selects(config["baskets"]["capture"], namespace):
            raise ValueError("that checkout is excluded by this machine's capture basket")
        try:
            result = store.write(capture(wanted, repo_id, config["machine_id"],
                                         untracked=args.untracked,
                                         policy=recovery_policy(config, repo_id)).to_dict())
        except (CaptureRefused, StoreRefused) as exc:
            raise ValueError(str(exc)) from None
        state = store.status(repo_id, result["version"])
        print(f"Snapshot {result['version']}: {state}. "
              + ("Written now." if result["written"] else result["reason"]))
        return 0
    if args.action == "preview":
        if not all((args.source, args.repo_id, args.version)):
            raise ValueError("recovery preview needs --source, --repo-id, and --version")
        from snapshot_preview import preview

        try:
            print(json.dumps(preview(store.read(args.source, args.repo_id, args.version)), indent=2))
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
        return 0
    if args.action == "restore":
        if not args.yes:
            raise ValueError("recovery restore creates a disposable checkout; review and re-run with --yes")
        if not all((args.source, args.repo_id, args.version, args.source_repo, args.destination)):
            raise ValueError("recovery restore needs --source, --repo-id, --version, --source-repo, and --destination")
        from snapshot_restore import RestoreRefused, prepare_disposable_checkout, restore

        try:
            body = store.read(args.source, args.repo_id, args.version)
            target = prepare_disposable_checkout(args.source_repo, body["base_commit"], args.destination)
            print(json.dumps(restore(body, target), indent=2))
        except (StoreRefused, RestoreRefused) as exc:
            raise ValueError(str(exc)) from None
        return 0
    if args.action == "acknowledge":
        if not args.yes:
            raise ValueError("recovery acknowledgement writes a verification record; re-run with --yes")
        if not all((args.source, args.repo_id, args.version)):
            raise ValueError("recovery acknowledge needs --source, --repo-id, and --version")
        try:
            record = store.acknowledge(args.source, args.repo_id, args.version)
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
        print(f"Acknowledged {record['source_machine']}/{record['repo_id'][:12]}… "
              f"version {record['version']}.")
        return 0
    if args.action == "retire":
        if not args.yes:
            raise ValueError("recovery retire deletes a local snapshot after proof; re-run with --yes")
        if args.repo is None or not args.version:
            raise ValueError("recovery retire needs --repo PATH and --version")
        from fleet_observer import IncrementalObserver
        from retirement import RetirementRefused, prove_retirement

        observer = IncrementalObserver(config)
        observer.inventory()
        wanted = args.repo.expanduser().resolve()
        repo_id = next((identity for identity, path in observer.local_repositories().items()
                        if path == wanted), None)
        if repo_id is None:
            raise ValueError("that checkout is not in this machine's observed inventory")
        try:
            proof = prove_retirement(wanted, store.read(config["machine_id"], repo_id, args.version))
            store.retire(repo_id, args.version)
        except (StoreRefused, RetirementRefused) as exc:
            raise ValueError(str(exc)) from None
        print("Retired the proven snapshot:\n" + json.dumps(proof, indent=2))
        return 0
    versions = store.versions()
    print(f"Recovery location: {location}\nSnapshots written by this machine: {len(versions)}")
    for version in versions:
        print(f"  {version.repo_id[:12]}… {version.version} — "
              f"{store.status(version.repo_id, version.version)}")
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


def preflight_state(port: int = DEFAULT_LOCAL_PORT) -> dict:
    """Read-only availability facts consumed by both setup and the standalone command."""
    git = shutil.which("git")
    gh = shutil.which("gh")
    git_ready = bool(git)
    gh_ready = False
    if gh:
        try:
            gh_ready = run_gh(["auth", "status"], check=False, timeout=30).returncode == 0
        except (GhError, OSError):
            pass
    try:
        from fleet_net import local_identity
        local_identity()
    except (OSError, ValueError):
        tailnet = False
    else:
        tailnet = True
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
        dashboard = "available"
    except OSError:
        dashboard = "unavailable (choose another local port)"
    finally:
        probe.close()
    home = Path.home()
    candidates = [Path(value) for value in (os.environ.get("OneDrive"),
                  os.environ.get("OneDriveConsumer"), os.environ.get("OneDriveCommercial"))
                  if value]
    candidates += [home / name for name in ("Dropbox", "Google Drive", "Nextcloud")]
    folders = []
    seen = set()
    for folder in candidates:
        if folder.is_dir() and str(folder.resolve()).casefold() not in seen:
            seen.add(str(folder.resolve()).casefold())
            folders.append(folder)
    return {"git": git_ready, "github": gh_ready, "tailnet": tailnet,
            "dashboard": dashboard == "available", "port": port, "folders": folders}


def render_preflight(state: dict) -> str:
    return ("Fleet preflight (read-only):\n"
            f"  Git:       {'ready' if state['git'] else 'not found — required'}\n"
            f"  GitHub:    {'ready' if state['github'] else 'unavailable — optional durable tier'}\n"
            f"  Tailscale: {'ready' if state['tailnet'] else 'not connected — optional live tier'}\n"
            f"  Dashboard port {state['port']}: {'available' if state['dashboard'] else 'unavailable'}\n"
            "  Likely sync folders: " + (", ".join(map(str, state["folders"])) if state["folders"]
                                          else "none detected; you may still specify one"))


def command_preflight(port: int = DEFAULT_LOCAL_PORT) -> int:
    """Report what setup can use now. Absence of an optional tier is not an error."""
    state = preflight_state(port)
    print(render_preflight(state))
    return 0 if state["git"] and state["dashboard"] else 2


def command_catchup(args, config: dict) -> int:
    """The first fleet mutation: narrowly safe, local, and always planned before application."""
    if args.apply and not args.yes:
        raise ValueError("catchup --apply requires --yes after you review the plan")
    from fleet_actions import apply_catchup, plan_catchup, render_catchup
    from fleet_observer import IncrementalObserver

    observer = IncrementalObserver(config)
    count = observer.inventory()
    print(f"Inventory found {count} observed repository(ies). Fetching their remotes without "
          "changing branches, indexes, or files.")
    plan = plan_catchup(observer.paths)
    print(render_catchup(plan))
    if not args.apply:
        return 0
    results = apply_catchup(plan)
    print()
    print(render_catchup(results, applied=True))
    print("Start or resume the peer to publish the newly observed status.")
    return 1 if any(item["action"] in {"fetch_failed", "pull_failed", "pull_needs_review"}
                    for item in results) else 0


def command_safe_to_wipe(config: dict) -> int:
    """A deliberately strict replacement audit. Unknown is never an all-clear."""
    from fleet_actions import plan_catchup
    from fleet_observer import IncrementalObserver
    from recovery_runtime import RecoveryRuntime
    from shared.git_facts import repo_facts

    observer = IncrementalObserver(config)
    count = observer.inventory()
    if not count:
        print("SAFE-TO-WIPE: unproven — no observed repositories. Nothing was fetched or changed.")
        return 1
    plan = plan_catchup(observer.paths)
    recovery = RecoveryRuntime(config, observer, log=lambda *_: None)
    recovered = []
    unsafe = []
    for item in plan:
        if item["action"] == "current":
            continue
        # A verified snapshot may cover uncommitted work, but never local commits that have
        # not reached an upstream.  `plan_catchup` deliberately stops at dirtiness, so inspect
        # this one extra fact before calling it replaceable.
        facts = repo_facts(item["path"])
        if (item["action"] == "dirty" and facts.get("upstream")
                and facts.get("ahead") == 0
                and recovery.current_snapshot_state(item["path"]) == "recoverable elsewhere"):
            recovered.append(item)
        else:
            unsafe.append(item)
    print("SAFE-TO-WIPE AUDIT (fresh fetch completed; no working tree was changed)")
    if not unsafe:
        if recovered:
            print(f"SAFE: {count - len(recovered)} clean/current checkout(s), plus "
                  f"{len(recovered)} dirty checkout(s) whose exact current work is verified "
                  "recoverable on another peer.")
        else:
            print(f"SAFE: all {count} observed checkouts are clean and current with their upstreams.")
        return 0
    print("NOT SAFE: this machine holds work or Git state that has not been proved replaceable:")
    for item in unsafe:
        print(f"  {item['name']}: {item['action'].replace('_', ' ')} — {item['detail']}")
    if recovered:
        print(f"  {len(recovered)} dirty checkout(s) are covered by an exact, peer-verified "
              "recovery snapshot; they do not block replacement.")
    print("Resolve every remaining item, then run this audit again. A snapshot counts only when "
          "it exactly matches current work and another peer has verified its checksum.")
    return 1


def command_audit(args, config: dict) -> int:
    """A fleet-scale report, deliberately without a repair side effect."""
    from fleet_actions import audit_repositories, render_audit
    from fleet_observer import IncrementalObserver

    observer = IncrementalObserver(config)
    count = observer.inventory()
    rows = audit_repositories(observer.paths)
    if args.json:
        print(json.dumps([{**row, "path": str(row["path"])} for row in rows], indent=2))
    else:
        print(f"Inventory found {count} observed repository(ies).")
        print(render_audit(rows))
    return 1 if any(item["findings"] != ["no audited issue"] for item in rows) else 0


def command_materialize(args, config: dict) -> int:
    if args.apply and not args.yes:
        raise ValueError("materialize --apply requires --yes after you review the plan")
    if not args.destination.is_dir():
        raise ValueError("materialize --destination must already be an existing folder")
    from fleet_actions import apply_materialize, plan_materialize, render_materialize
    from fleet_observer import IncrementalObserver

    observer = IncrementalObserver(config)
    count = observer.inventory()
    plan = plan_materialize(observer.paths, args.destination)
    print(f"Inventory found {count} observed repository(ies).\n{render_materialize(plan)}")
    if not args.apply:
        return 0
    results = apply_materialize(plan)
    print("\n" + render_materialize(results, applied=True))
    return 1 if any(row["action"] == "clone_failed" for row in results) else 0


def command_live_buffers(args, config: dict) -> int:
    """The live tier's local first slice: no watcher, no content publication."""
    from vscode_buffers import default_backup_root, inspect

    root = args.backup_root or default_backup_root()
    if root is None or not root.is_dir():
        raise ValueError("select an existing VS Code Backups folder with --backup-root")
    items = inspect(config["roots"], root)
    print(json.dumps({"buffers": items,
                      "note": "Explicit local metadata only; no editor buffer content was sent or stored."},
                     indent=2))
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
        if args.command == "preflight":
            return command_preflight()
        if args.command == "rescan":
            if not (directory / APP_CONFIG).exists():
                raise ValueError("no saved fleet configuration")
            atomic_write_bytes(directory / "fleet-rescan.request", b"inventory requested\n")
            print("Requested one local inventory refresh; the running peer will perform it.")
            return 0
        if args.command == "transports":
            return command_transports(args, directory)
        if args.command == "baskets":
            return command_baskets(args, directory)
        if args.command == "recovery":
            return command_recovery(args, directory)
        if args.command == "git-client":
            from git_client import discover_clients, LABELS, validate_choice

            config = load_saved(directory)
            if args.disable and (args.client or args.executable):
                raise ValueError("choose --disable or a client")
            if args.executable and not args.client:
                raise ValueError("--executable needs --client")
            if args.client:
                choice = ({"id": args.client, "executable": str(args.executable.expanduser().resolve())}
                          if args.executable else discover_clients().get(args.client))
                if not choice or not Path(choice["executable"]).is_file():
                    raise ValueError("client not found; pass --executable with its installed location")
                validate_choice(choice)
                config["git_client"] = choice
                write_json(directory / APP_CONFIG, config)
                print(f"Selected {LABELS[args.client]}. Resume the peer to use its desktop shortcut.")
            elif args.disable:
                config["git_client"] = None
                write_json(directory / APP_CONFIG, config)
                print("Desktop shortcut disabled.")
            else:
                print(json.dumps({"selected": config.get("git_client"),
                                  "detected": discover_clients(config.get("git_client"))}, indent=2))
            return 0
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
        if args.command == "catchup":
            return command_catchup(args, config)
        if args.command == "safe-to-wipe":
            return command_safe_to_wipe(config)
        if args.command == "audit":
            return command_audit(args, config)
        if args.command == "materialize":
            return command_materialize(args, config)
        if args.command == "live-buffers":
            return command_live_buffers(args, config)

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
    if args.command == "setup" and not args.configure_only:
        # Setup ends with the app running where you can see it -- a tray icon on Windows -- not
        # a terminal you have to keep open. The lock is released before the tray starts, because
        # the tray's own worker takes it for the running peer.
        directory = args.config_dir.expanduser()
        try:
            with app_lock(directory):
                code = _main([*argv, "--configure-only"])
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if code:
            return code
        inner = ["--config-dir", str(directory), "tray"]
        offer_start_at_login(inner)
        return main(inner, stopping, on_ready)
    if args.command in ("doctor", "rescan", "preflight"):
        return _main(argv, stopping, on_ready)
    try:
        with app_lock(args.config_dir.expanduser()):
            return _main(argv, stopping, on_ready)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
