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
import os
import signal
import shutil
import socket
import sys
import threading
from pathlib import Path


from Basic import _cli  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._providers.github import GhError, run_gh  # noqa: E402
from Special._settings.fleet import (ensure_fleet_settings, fleet_directory, fleet_home,  # noqa: E402
                                    load_fleet_settings)
from Special._sync.config import default_machine_id  # noqa: E402
from Elaborate._fleet.config import (DEFAULT_FOLDER_SECONDS, DEFAULT_LOCAL_PORT,  # noqa: E402
                          DEFAULT_REPO_SECONDS, DEFAULT_TAILNET_PORT, describe,
                          new_config, policy_record, recovery_policy, save_saved, validate)
from Elaborate._fleet.peer import run_peer  # noqa: E402
from Special._sync.lock import app_lock  # noqa: E402

#: What start-at-sign-in launches: the App's tray, by path (Elaborate never imports App).
TRAY_SCRIPT = Path(__file__).resolve().parents[2] / "App" / "tray.py"
from Basic._files import atomic_write_bytes  # noqa: E402
from Special._sync.manifest import fleet_id_for, is_fleet_secret, new_fleet_secret  # noqa: E402
from Elaborate._transport.repo import RepoTransport, create_state_repo  # noqa: E402


def _say(*parts, file=None, sep=" ", end="\n", flush=False) -> None:
    """A guided step's line, in the station style (print's signature, for the guided prompts)."""
    from Basic._station import line, say
    text = sep.join(str(part) for part in parts)
    for piece in text.splitlines() or [""]:
        line(piece) if piece.strip() else say()


def _ask(prompt: str) -> str:
    return input("  " + prompt)


def load_saved(directory: Path, *, home=None) -> dict:
    """Read this machine's app enrollment from the settings profile. Loading never writes."""
    snapshot = load_fleet_settings(home)
    config = snapshot.config("app") if snapshot is not None else None
    if config is None:
        raise ValueError("this machine is not enrolled; enroll it with: gitso machine add <library folder>")
    return validate(config)


def profile_arguments(directory, home=None):
    """Keep both profile and local state selection in tray/setup/autostart handoffs."""
    return ["--config-dir", str(directory), "--settings-home", str(fleet_home(home))]


def offer_start_at_login(inner: list[str]) -> None:
    """Ask once at the end of setup. Declining is fine; the tray menu can turn it on later."""
    try:
        answer = _ask("Start gitSpecOps automatically when you log in? [Y/n]: ").strip().lower()
    except EOFError:
        return
    if answer in ("n", "no"):
        _say("Start at login left off. Turn it on later from the tray menu, or run "
              "'fleet autostart enable'.")
        return
    import Elaborate._fleet.autostart as fleet_autostart

    try:
        result = fleet_autostart.enable(inner, script=TRAY_SCRIPT)
        _say(f"Start at login enabled ({result['method']}).")
    except (OSError, ValueError) as exc:
        _say(f"Could not enable start at login: {exc}")


def require_gh():
    # Capture output: gh status can include credential metadata. Never print or store it.
    proc = run_gh(["auth", "status"], check=False, timeout=30)
    if proc.returncode:
        raise ValueError("a working gh login is required for the GitHub state repository; "
                         "check 'gh auth status'")


def resolve_machine_identity(want_tailnet: bool) -> tuple[str, str]:
    """A stable id for this peer, preferring Tailscale's node id when the tier is wanted.

    Falls back to the fleet's machine id (hostname-derived, overridable) so that a peer
    can exist with Tailscale absent — which is the whole point of the peer model.
    """
    if want_tailnet:
        try:
            from Elaborate._fleet.net import local_identity

            identity = local_identity()
            return identity["machine_id"], identity["label"]
        except (OSError, ValueError) as exc:
            _say(f"note: Tailscale is not usable right now ({exc}); this peer will use its "
                  "local machine id and enable the tailnet tier when Tailscale returns.",
                  flush=True)
    name = default_machine_id()
    return name, name


def configure(args, directory: Path) -> dict:
    home = getattr(args, "settings_home", None)
    snapshot = ensure_fleet_settings(home)
    if snapshot is not None:
        if snapshot.config("app") is not None:
            raise ValueError("app enrollment already exists; resume it or select a settings command")
        snapshot.check_roots("app", args.root or [])
        snapshot.check_identity(label=args.label, secret=args.fleet_secret)
        definitions = {}
        if args.folder:
            definitions["folder"] = {"path": str(Path(args.folder).expanduser().absolute()), "seconds": args.folder_seconds}
        if args.repo:
            definitions["repo"] = {"name": args.repo, "seconds": args.repo_seconds}
        if not args.no_tailnet:
            definitions["tailnet"] = {"port": args.tailnet_port, "allowed_login": None}
        snapshot.transport_changes("app", definitions)
    if not args.root:
        raise ValueError("select your repository library with --root PATH (repeatable)")
    if any(not Path(root).expanduser().is_dir() for root in args.root):
        raise ValueError("every configured repository root must exist")
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

    machine = snapshot.document.get("machine") if snapshot is not None else None
    machine_id, label = ((machine["id"], machine["label"]) if machine else
                         resolve_machine_identity("tailnet" in transports))
    secret = args.fleet_secret or (machine["fleet_secret"] if machine else new_fleet_secret())
    if not is_fleet_secret(secret):
        raise ValueError("--fleet-secret must be 64 hexadecimal characters")
    config = new_config(machine_id, args.label or label, args.root, secret,
                        debounce_seconds=args.debounce_seconds, local_port=args.local_port,
                        transports=transports, share_names=not args.withhold_names)
    validate(config)
    path = save_saved(directory, config, home=home, snapshot=snapshot)
    config = load_saved(directory, home=home)
    _say(f"Saved: {path}\nTransports:\n{describe(config)}")
    if not args.fleet_secret and machine is None:
        _say(f"\nCreated fleet {fleet_id_for(secret)}. The key is hidden. "
              "Use 'gitso fleet key --show' only where you mean to display it, when joining another machine.")
    return config


def build_parser():
    # `gitso fleet doctor` reaches the `fleet doctor` subcommand: name it once, not twice, in its usage.
    # gitso passes the words before the subcommand (`gitso fleet`, `gitso machine`, `gitso`).
    parser = argparse.ArgumentParser(prog=sys.argv[0] if sys.argv[0].startswith("gitso") else "gitso fleet",
                                     description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    _cli.add_json(parser)
    parser.add_argument("--config-dir", type=Path, help="local fleet state directory")
    parser.add_argument("--settings-home", type=Path, help="common profile; defaults to the user-data home")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="guided first-run setup for this peer")
    setup.add_argument("--configure-only", action="store_true",
                       help="save the configuration and exit instead of starting")

    peer = commands.add_parser("join", help="enroll, join and start this peer in one step (shows the plan first)")
    peer.add_argument("--root", action="append", help="repository library, inventoried once")
    peer.add_argument("--label", help="display name; independent of the stable machine id")
    peer.add_argument("--fleet-secret", help="join an existing fleet (64 hex characters)")
    peer.add_argument("--debounce-seconds", type=float, default=0.75)
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
    peer.add_argument("--withhold-names", action="store_true",
                      help="publish salted ids only, not repository names, branches and commits")
    peer.add_argument("--configure-only", action="store_true")

    commands.add_parser("run", help="resume this peer; installs no service")
    commands.add_parser("doctor", help="show configuration and reachability; hides the secret")
    key = commands.add_parser("key", help="the fleet key's details, without logs or writes")
    key.add_argument("--show", action="store_true", help="print the raw key here; any agent capturing this output will receive it")
    commands.add_parser("preflight", help="check setup prerequisites and optional tiers without changing anything")
    commands.add_parser("rescan", help="request one deliberate local inventory refresh")
    commands.add_parser("safe-to-wipe",
                        help="fresh-fetch every observed checkout and report whether this machine is replaceable")
    commands.add_parser("leave", help="stop sharing with the fleet; the machine stays enrolled")
    status = commands.add_parser("status", help="what is set up, and what each next tier unlocks")
    status.add_argument("--readiness", action="store_true",
                        help="also check Git, the gh login, Tailscale and sync folders")
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
    recovery.add_argument("--source", help="source machine id when acknowledging a peer snapshot")
    recovery.add_argument("--repo-id", help="opaque repository id when acknowledging a peer snapshot")
    recovery.add_argument("--version", help="snapshot version when acknowledging a peer snapshot")
    recovery.add_argument("--source-repo", type=Path,
                          help="local repository holding a snapshot base, for disposable restore")
    recovery.add_argument("--destination", type=Path,
                          help="new or empty disposable checkout destination, for restore")

    autostart = commands.add_parser("start-at-sign-in", help="inspect or change starting the tray at sign-in")
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
    for name, sub in commands.choices.items():
        _cli.add_json(sub, sub=True)
        if name in ("join", "leave", "recovery"):
            _cli.add_apply(sub)
    return parser


def guided_durable_arguments() -> list[str]:
    """Prepare an explicit repo choice; creation happens only in configure()."""
    if _ask("Set up durable status in a private GitHub repository? [y/N]: ").strip().lower() \
            not in ("y", "yes"):
        return []
    require_gh()
    suggestion = ""
    try:
        login = run_gh(["api", "user", "--jq", ".login"], timeout=30).stdout.strip()
        candidate = f"{login}/gitspecops-state"
        RepoTransport(candidate)  # validate before presenting CLI output as a name
        suggestion = candidate
    except (GhError, OSError, ValueError):
        _say("Could not suggest an owner; enter an accessible owner/name below.")
    _say("\nUse a dedicated private repository that gitSpecOps manages. The app creates or\n"
          "replaces its machine status files under machines/ using your existing gh login.\n"
          "It publishes initial status when started, then changes at most once every "
          f"{DEFAULT_REPO_SECONDS // 60} minutes.\n"
          "Changes waiting for that interval are kept for later delivery while the app runs;\n"
          "failed writes retry after the interval. Stopping the app can leave changes unsent.\n"
          "This stores status only: no source files, repository history, or recovery snapshots.\n"
          "By default each status file names your repositories, branches and current commits,\n"
          "so every machine can show what the others hold (you can withhold names below).\n"
          "You can inspect the repository; gitSpecOps never clones it.\n")
    prompt = f"State repository [{suggestion}]: " if suggestion else "State repository owner/name: "
    spec = _ask(prompt).strip() or suggestion
    if not spec:
        _say("Durable status skipped.")
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
    if _ask(f"Type {confirmation} to {action} [Enter skips]: ").strip() != confirmation:
        _say("Durable status skipped; no repository will be created or used.")
        return []
    return ["--repo", spec, *extra]


def guided_tailnet_join_secret() -> str:
    """Offer a deliberate, authenticated key hand-off from a running peer.

    The endpoint is reachable only over the tailnet and authorizes the caller with Tailscale's
    identity check.  It is still opt-in: a wrong or unavailable peer must fall back to the
    manual key rather than making setup look as though it joined a fleet when it did not.
    """
    if _ask("Join a running peer over Tailscale instead of pasting a fleet key? [y/N]: ").strip().lower() \
            not in ("y", "yes"):
        return ""
    try:
        from Elaborate._fleet.net import FleetClient, discover_hosts

        hosts = [item for item in discover_hosts() if item.get("serving")]
        if not hosts:
            _say("No running fleet peer was found. Paste a fleet key instead, or start one peer first.")
            return ""
        for index, host in enumerate(hosts, start=1):
            _say(f"  {index}. {host['label']}")
        answer = _ask("Peer number [Enter cancels]: ").strip()
        if not answer:
            return ""
        host = hosts[int(answer) - 1]
        session = FleetClient(host["url"]).request("/v1/session")
        secret = session.get("fleet_secret") if isinstance(session, dict) else None
        if not is_fleet_secret(secret):
            raise ValueError("peer returned no valid fleet key")
        _say(f"Joined fleet {fleet_id_for(secret)} through authenticated peer {host['label']}.")
        return secret
    except (IndexError, OSError, ValueError) as exc:
        _say(f"Could not join a peer ({exc}). Paste a fleet key instead.")
        return ""



def guided_fleet_setup(directory: Path, *, home=None) -> int:
    """Join this enrolled machine to a fleet: a key (new or existing), then how it shares status.

    The machine's libraries are its own enrollment (Special/machine.py); this asks only
    the fleet's questions and offers every transport, requiring none."""
    from Special._settings.fleet import replace_fleet_secret

    snapshot = load_fleet_settings(home)
    config = snapshot.config("app") if snapshot is not None else None
    if config is None:
        raise ValueError("this machine is not enrolled; enroll it with: gitso machine add <library folder>")
    _say("Fleet setup. This machine is enrolled; now it joins a fleet. Every machine is a peer:\n"
          "it publishes what it sees and reads what the others publish. None is in charge.\n")
    readiness = preflight_state(int(config["local_port"]))
    _say(render_preflight(readiness))
    secret = _ask("Fleet key from a machine already in your fleet [start a new fleet]: ").strip()
    if not secret and readiness["tailnet"]:
        secret = guided_tailnet_join_secret()
    if secret:
        if not is_fleet_secret(secret):
            raise ValueError("a fleet key is 64 hexadecimal characters")
        if secret.lower() != config["fleet_secret"].lower():
            replace_fleet_secret(secret, home=home, snapshot=snapshot)
            _say("Joined the fleet with that key.")
    arguments = []
    if readiness["github"]:
        arguments += guided_durable_arguments()
    else:
        _say("GitHub durable status skipped: gh is unavailable or not logged in.")
    suggested = readiness["folders"][0] if readiness["folders"] else ""
    folder = (_ask(f"A folder your sync client already replicates [{suggested or 'none'}]: ")
              .strip().strip('"') or suggested)
    if folder:
        arguments += ["--folder", folder]
    if not readiness["tailnet"]:
        _say("Tailscale live sharing skipped: it is not connected. Add it later with "
              "gitso fleet transports --tailnet.")
    elif _ask("Talk directly to your other machines over Tailscale? [Y/n]: ").strip().lower() \
            not in ("n", "no"):
        arguments.append("--tailnet")
    if not arguments:
        _say("No transport chosen: this machine stays on its own. Run this again any time.")
        return 0
    from Elaborate._fleet.setup_state import apply_transports
    chosen = build_parser().parse_args([*profile_arguments(directory, home), "transports", *arguments])
    config = apply_transports(
        load_saved(directory, home=home), folder=chosen.folder, clear_folder=False,
        folder_seconds=chosen.folder_seconds, repo=chosen.repo, create_repo=chosen.create_repo,
        clear_repo=False, repo_seconds=chosen.repo_seconds, tailnet=chosen.tailnet,
        clear_tailnet=False, tailnet_port=chosen.tailnet_port, directory=directory, home=home)
    _say(f"Transports now:\n{describe(config)}")
    _say("\nYour other machines see this one's repository names, branches and current commits,\n"
          "so each can show what the others hold. Without names they see salted ids only."
          + ("\nA synced folder's provider (Dropbox, ...) can read those names too." if folder else ""))
    if _ask("Share names with your other machines? [Y/n]: ").strip().lower() in ("n", "no"):
        config = load_saved(directory, home=home)
        config["share_names"] = False
        save_saved(directory, config, home=home)
    return 0


def command_leave(directory: Path, out=None, approval=None, *, home=None) -> int:
    """Stop sharing with the fleet: deselect every transport. The machine stays enrolled.
    A trusted caller passing no `approval` has approved already."""
    out = out or _cli.Out(None, "fleet leave", PAGES["leave"])
    config = load_saved(directory, home=home)
    if not config.get("transports"):
        return out.finish(message="This machine shares with no fleet; nothing to leave.")
    plan = {"action": "leave", "transports": sorted(config["transports"])}
    if approval is not None and not approval.decide(plan, lambda: _cli.outline("Stop sharing through", plan),
                                                    question="Leave the fleet?"):
        return approval.code
    config["transports"] = {}
    save_saved(directory, config, home=home)
    return out.finish(message="Left the fleet: no transport is selected. This machine keeps its libraries "
                              "and its web view; its last published status stays wherever it was published.")


def command_transports(args, directory: Path, out) -> int:
    """One explicit change, made at once: which ways this machine shares (like a setting)."""
    from Elaborate._fleet.setup_state import apply_transports

    home = getattr(args, "settings_home", None)
    config = apply_transports(
        load_saved(directory, home=home), folder=args.folder, clear_folder=args.clear_folder,
        folder_seconds=args.folder_seconds, repo=args.repo, create_repo=args.create_repo,
        clear_repo=args.clear_repo, repo_seconds=args.repo_seconds, tailnet=args.tailnet,
        clear_tailnet=args.clear_tailnet, tailnet_port=args.tailnet_port, directory=directory, home=home)
    out.say(f"Transports now:\n{describe(config)}")
    out.data(transports=config.get("transports") or {})
    return out.finish(message="Saved. Start sharing with gitso peer run, or the tray.")


def command_status(args, out) -> int:
    """What is set up, what each next tier needs, and what it unlocks. Works unenrolled too."""
    from Elaborate._fleet.setup_state import setup_state

    state = setup_state(args.settings_home, args.config_dir, readiness=args.readiness)
    out.data(**state)
    machine = state["machine"]
    out.say("This machine: " + (f"{machine['label']}, libraries: {', '.join(machine['libraries'])}"
                                if machine else "not enrolled"))
    if state["fleet"]:
        out.say(f"Fleet {state['fleet']['fleet_id']} through: {', '.join(state['fleet']['transports'])}")
    for tier in state["tiers"]:
        mark = "x" if tier["reached"] else (">" if tier["id"] == state["next"] else " ")
        out.say(f"\n[{mark}] {tier['title']}  (adds: {tier['needs']})")
        for item in tier["unlocks"]:
            out.say(f"      {item['text']}" + ("" if item["built"] else "  (planned)"))
    if state["next"] == "machine":
        out.say("\nNext: gitso machine add <library folder>")
    elif state["next"]:
        out.say("\nNext: gitso fleet   (or the tray, then its setup page)")
    return out.finish()


def command_baskets(args, directory: Path, out) -> int:
    """Show, or change one scope (a setting, made at once). Capture stays off until recovery is set up."""
    import Special._sync.baskets as baskets

    config = load_saved(directory, home=getattr(args, "settings_home", None))
    scopes = config.get("baskets") or copy.deepcopy(baskets.DEFAULT_SCOPES)
    if not args.scope:
        out.data(baskets=scopes)
        out.say(f"Baskets on this machine:\n{baskets.describe(scopes)}\n\n"
                "Namespaces are host/owner, e.g. github.com/your-org. Observing and publishing are\n"
                "separate: narrowing 'publish' keeps a repository visible here while hiding its\n"
                "state from every other machine.")
        return out.finish()
    if not args.mode:
        raise ValueError("--scope needs --mode")
    selection = baskets.parse_selection(args.mode, args.namespace)
    scopes = {**scopes, args.scope: selection}
    config["baskets"] = baskets.validate_scopes(scopes)
    validate(config)
    save_saved(directory, config, home=getattr(args, "settings_home", None))
    out.data(baskets=scopes)
    out.say(f"Baskets now:\n{baskets.describe(scopes)}")
    if args.scope == "observe":
        out.say("\nRun 'gitso peer rescan' (or restart the peer) to apply this to the inventory.")
    elif args.scope == "capture":
        out.say("\nCapture selection is local-only. With a separately confirmed recovery location, "
                "the running peer captures selected repositories after filesystem quiet periods.")
    else:
        out.say("\nWithheld repositories stay on your local dashboard and are published to nothing.")
    return out.finish()


def _observed(config, wanted):
    from Special._sync.inventory import IncrementalObserver

    observer = IncrementalObserver(config)
    observer.inventory()
    repo_id = next((identity for identity, path in observer.local_repositories().items()
                    if path == wanted), None)
    if repo_id is None:
        raise ValueError("that checkout is not in this machine's observed inventory")
    return observer, repo_id


def command_recovery(args, directory: Path, out, approval) -> int:
    """Configure the content tier separately from names-free status transports.

    Anything that copies source content, writes a record or deletes a snapshot shows its plan first
    and runs on approval (--apply PLAN_ID, or yes at a terminal)."""
    from Elaborate._recovery.snapshot_store import SnapshotStore, StoreRefused, validate_location

    home = getattr(args, "settings_home", None)
    config = load_saved(directory, home=home)
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
        location = str(args.location.expanduser().resolve())
        plan = {"action": "configure", "location": location, "warnings": warnings}

        def show():
            out.say(f"Recovery location: {location}")
            for item in warnings:
                out.say(f"warning: {item}")
            for text in out.lines:
                from Basic._station import line
                line(text)
            out.lines.clear()

        if not approval.decide(plan, show, question="Use this location for snapshots of unfinished work?"):
            return approval.code
        recovery["location"] = location
        recovery["confirmed"] = True
        config["recovery"] = recovery
        validate(config)
        save_saved(directory, config, home=home)
        return out.finish(message="Recovery location saved. It is separate from status publication; "
                                  "configuring it captures no file.")
    location = recovery["location"]
    if location is None:
        return out.finish(message="Recovery is not configured. Use: gitso recovery configure --location PATH")
    store = SnapshotStore(location, config["machine_id"])
    if args.action == "policy":
        if args.repo is None:
            raise ValueError("recovery policy needs --repo PATH")
        _observer, repo_id = _observed(config, args.repo.expanduser().resolve())
        current = recovery_policy(config, repo_id)
        changed = any((args.obey_gitignore, args.secret_protection,
                       args.allow_path is not None, args.clear_allow_paths))
        if not changed:
            out.data(repo_id=repo_id, policy=policy_record(current))
            return out.finish(rows=True)
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
        plan = {"action": "policy", "repo_id": repo_id, "policy": policy_record(updated),
                "weakens_default_protection": relaxed}
        if relaxed and not approval.decide(plan, lambda: _cli.outline("This policy weakens capture's "
                                                                      "default protection", plan),
                                           question="Save this weaker policy?"):
            return approval.code
        recovery["policies"] = {**recovery["policies"], repo_id: policy_record(updated)}
        config["recovery"] = recovery
        validate(config)
        save_saved(directory, config, home=home)
        out.data(repo_id=repo_id, policy=policy_record(updated))
        return out.finish(rows=True, message="Saved local-only recovery policy.")
    if args.action == "capture":
        if args.repo is None:
            raise ValueError("recovery capture needs --repo PATH")
        from Elaborate._recovery.capture import CaptureRefused, capture
        import Special._sync.baskets as baskets

        wanted = args.repo.expanduser().resolve()
        observer, repo_id = _observed(config, wanted)
        namespace = observer.namespaces().get(repo_id)
        if not namespace or not baskets.selects(config["baskets"]["capture"], namespace):
            raise ValueError("that checkout is excluded by this machine's capture basket")
        plan = {"action": "capture", "repo": str(wanted), "repo_id": repo_id, "untracked": list(args.untracked),
                "location": location}
        if not approval.decide(plan, lambda: _cli.outline("Copy this checkout's unfinished work to the "
                                                          "recovery location", plan),
                               question="Capture it?"):
            return approval.code
        try:
            result = store.write(capture(wanted, repo_id, config["machine_id"],
                                         untracked=args.untracked,
                                         policy=recovery_policy(config, repo_id)).to_dict())
        except (CaptureRefused, StoreRefused) as exc:
            raise ValueError(str(exc)) from None
        state = store.status(repo_id, result["version"])
        out.data(version=result["version"], state=state, written=result["written"])
        return out.finish(message=f"Snapshot {result['version']}: {state}. "
                                  + ("Written now." if result["written"] else result["reason"]))
    if args.action == "preview":
        if not all((args.source, args.repo_id, args.version)):
            raise ValueError("recovery preview needs --source, --repo-id, and --version")
        from Elaborate._recovery.snapshot_preview import preview

        try:
            out.data(preview=preview(store.read(args.source, args.repo_id, args.version)))
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
        return out.finish(rows=True)
    if args.action == "restore":
        if not all((args.source, args.repo_id, args.version, args.source_repo, args.destination)):
            raise ValueError("recovery restore needs --source, --repo-id, --version, --source-repo, and --destination")
        from Elaborate._recovery.snapshot_restore import RestoreRefused, prepare_disposable_checkout, restore

        plan = {"action": "restore", "source": args.source, "repo_id": args.repo_id, "version": args.version,
                "source_repo": str(args.source_repo), "destination": str(args.destination)}
        if not approval.decide(plan, lambda: _cli.outline("Restore into a new, disposable checkout", plan),
                               question="Restore it?"):
            return approval.code
        try:
            body = store.read(args.source, args.repo_id, args.version)
            target = prepare_disposable_checkout(args.source_repo, body["base_commit"], args.destination)
            out.data(restore=restore(body, target))
        except (StoreRefused, RestoreRefused) as exc:
            raise ValueError(str(exc)) from None
        return out.finish(rows=True, message="Restored into a disposable checkout.")
    if args.action == "acknowledge":
        if not all((args.source, args.repo_id, args.version)):
            raise ValueError("recovery acknowledge needs --source, --repo-id, and --version")
        plan = {"action": "acknowledge", "source": args.source, "repo_id": args.repo_id, "version": args.version}
        if not approval.decide(plan, lambda: _cli.outline("Record that this snapshot was verified", plan),
                               question="Acknowledge it?"):
            return approval.code
        try:
            record = store.acknowledge(args.source, args.repo_id, args.version)
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
        out.data(acknowledged=record)
        return out.finish(message=f"Acknowledged {record['source_machine']}/{record['repo_id'][:12]}… "
                                  f"version {record['version']}.")
    if args.action == "retire":
        if args.repo is None or not args.version:
            raise ValueError("recovery retire needs --repo PATH and --version")
        from Elaborate._recovery.retirement import RetirementRefused, prove_retirement

        wanted = args.repo.expanduser().resolve()
        _observer, repo_id = _observed(config, wanted)
        try:
            proof = prove_retirement(wanted, store.read(config["machine_id"], repo_id, args.version))
        except (StoreRefused, RetirementRefused) as exc:
            raise ValueError(str(exc)) from None
        plan = {"action": "retire", "repo_id": repo_id, "version": args.version, "proof": proof}
        if not approval.decide(plan, lambda: _cli.outline("Delete this snapshot: its work is proven to be "
                                                          "in the checkout", plan),
                               question="Retire it?"):
            return approval.code
        try:
            store.retire(repo_id, args.version)
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
        out.data(proof=proof)
        return out.finish(rows=True, message="Retired the proven snapshot.")
    versions = store.versions()
    out.data(location=location, snapshots=[{"repo_id": version.repo_id, "version": version.version,
                                            "state": store.status(version.repo_id, version.version)}
                                           for version in versions])
    out.say(f"Recovery location: {location}\nSnapshots written by this machine: {len(versions)}")
    for version in versions:
        out.say(f"  {version.repo_id[:12]}… {version.version} — "
                f"{store.status(version.repo_id, version.version)}")
    return out.finish()


def command_doctor(config: dict, out) -> int:
    shown = {k: v for k, v in config.items() if k != "fleet_secret"}
    out.data(configuration=shown, fleet_id=fleet_id_for(config["fleet_secret"]),
             dashboard=f"http://127.0.0.1:{config['local_port']}/")
    out.say(f"fleet id: {fleet_id_for(config['fleet_secret'])}  (key is set and hidden)")
    out.say(f"dashboard: http://127.0.0.1:{config['local_port']}/  — local, always available")
    peers_seen = []
    if (config.get("transports") or {}).get("tailnet"):
        try:
            from Elaborate._fleet.net import discover_hosts

            port = config["transports"]["tailnet"]["port"]
            peers = discover_hosts(port=port, timeout=0.6)
            for peer in peers:
                state = "answering" if peer["serving"] else (
                    "online, not running the app" if peer["online"] else "offline")
                peers_seen.append({"label": peer["label"], "state": state})
                out.say(f"  peer {peer['label']:<20} {state}")
            if not peers:
                out.say("  no tailnet peers found")
        except (OSError, ValueError) as exc:
            out.say(f"  tailnet unavailable: {exc}")
    out.data(peers=peers_seen)
    return out.finish(rows=True)


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
        from Elaborate._fleet.net import local_identity
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
    return ("What this computer has for a fleet (read-only):\n"
            f"  Git:       {'ready' if state['git'] else 'not found — required'}\n"
            f"  GitHub:    {'ready' if state['github'] else 'unavailable — optional durable tier'}\n"
            f"  Tailscale: {'ready' if state['tailnet'] else 'not connected — optional live tier'}\n"
            f"  Dashboard port {state['port']}: {'available' if state['dashboard'] else 'unavailable'}\n"
            "  Likely sync folders: " + (", ".join(map(str, state["folders"])) if state["folders"]
                                          else "none detected; you may still specify one"))


def command_preflight(out, port: int = DEFAULT_LOCAL_PORT) -> int:
    """Report what setup can use now. Absence of an optional tier is not an error."""
    state = preflight_state(port)
    out.data(**{**state, "folders": [str(folder) for folder in state["folders"]]})
    out.say(render_preflight(state))
    ready = state["git"] and state["dashboard"]
    return out.finish(ready, _cli.OK if ready else _cli.USAGE)


def command_safe_to_wipe(config: dict, out=None) -> int:
    """A deliberately strict replacement audit. Unknown is never an all-clear.

    It walks the configured roots itself instead of trusting the fleet observer, which skips
    repositories it cannot name and judges only the current branch (see fleet_actions.plan_wipe).
    """
    from Special._sync.actions import plan_wipe, render_wipe
    from Special._sync.inventory import IncrementalObserver
    from Elaborate._recovery.runtime import RecoveryRuntime

    out = out or _cli.Out(None, "machine safe-to-wipe", PAGES["safe-to-wipe"])
    observer = IncrementalObserver(config)
    observer.inventory()  # only to let recovery match a checkout to its repository id
    recovery = RecoveryRuntime(config, observer, log=lambda *_: None)
    rows = plan_wipe(config["roots"], recoverable=lambda path: (
        recovery.current_snapshot_state(path) == "recoverable elsewhere"))
    text, safe = render_wipe(rows)
    out.data(safe=safe, repositories=[{key: str(value) if isinstance(value, Path) else value
                                       for key, value in row.items()} for row in rows])
    out.say(text)
    return out.finish(safe)


def run_autostart(args, out) -> int:
    """Start at sign-in: status, or an explicit on/off (a setting, made at once)."""
    import Elaborate._fleet.autostart as fleet_autostart

    inner = profile_arguments(args.config_dir, args.settings_home)
    if args.systemd and sys.platform.startswith("linux"):
        if args.action == "enable":
            target = fleet_autostart.systemd_enable(
                fleet_autostart.launch_command(inner, script=TRAY_SCRIPT))
            out.data(method="systemd --user", enabled=True, unit=str(target))
            return out.finish(message="Start at sign-in turned on with systemd --user. Without "
                                      "'loginctl enable-linger' it runs only while you are signed in.")
        if args.action == "disable":
            out.data(method="systemd --user", enabled=False, removed=str(fleet_autostart.systemd_disable()))
            return out.finish(message="Start at sign-in turned off.")
        out.data(method="systemd --user", enabled=fleet_autostart._systemd_unit_path().is_file())
        return out.finish(rows=True)
    if args.action == "enable":
        out.data(**fleet_autostart.enable(inner, script=TRAY_SCRIPT))
        return out.finish(rows=True, message="Start at sign-in turned on.")
    if args.action == "disable":
        out.data(**fleet_autostart.disable())
        return out.finish(rows=True, message="Start at sign-in turned off.")
    out.data(**fleet_autostart.status())
    return out.finish(rows=True)


#: Each fleet subcommand's page title on a screen.
PAGES = {"setup": "Fleet setup", "peer": "Peer", "run": "Peer", "doctor": "Doctor",
         "key": "Fleet key", "preflight": "Preflight", "rescan": "Rescan",
         "safe-to-wipe": "Safe to wipe?", "leave": "Leave the fleet", "status": "Setup status",
         "git-client": "Desktop Git app", "baskets": "Baskets", "recovery": "Recovery",
         "start-at-sign-in": "Start at sign-in", "transports": "Transports"}


def _program_words() -> list[str]:
    """The words gitso put before the subcommand: ["fleet"], ["machine"], [] for `gitso recovery`."""
    program = sys.argv[0] if sys.argv and sys.argv[0].startswith("gitso") else "gitso fleet"
    return program.split()[1:]


def _command_name(args) -> str:
    """The command as typed: `fleet join`, `machine safe-to-wipe`, `recovery`, `peer run`."""
    words = _program_words()
    return " ".join(words + ([args.command] if args.command not in words else []))


def _approval(args, argv):
    """Plans apply with the command as typed: the subcommand first, then everything else."""
    argv = list(argv)
    if args.command in argv:
        argv.remove(args.command)
    return _cli.Approval(args, " ".join([*_program_words(), args.command]), argv)


def _peer_plan(args) -> dict:
    """What starting a new peer would look through and share: shown before anything is read."""
    return {"action": "peer", "inventory_once_recursively": [str(Path(root).expanduser().resolve())
                                                             for root in args.root or []],
            "label": args.label, "joins_existing_fleet": bool(args.fleet_secret),
            "folder": args.folder, "repo": args.repo, "create_repo": args.create_repo,
            "tailnet": not args.no_tailnet, "share_names": not args.withhold_names}


def _main(argv=None, stopping=None, on_ready=None, serve=None):
    """`stopping`/`on_ready` are the shell seam used by fleet_tray.py.

    A caller supplying `stopping` owns the lifecycle and may not be on the main thread, so
    signal handlers are registered only for a plain foreground run — `signal.signal` raises
    off the main thread.
    """
    enable_unicode_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    name = _command_name(args)
    out = _cli.Out(args, name, PAGES.get(args.command, "Fleet"))
    approval = _approval(args, argv)
    try:
        if args.command == "preflight":
            return command_preflight(out)
        if args.command == "status":
            return command_status(args, out)
        directory = fleet_directory(args.config_dir, home=args.settings_home)
        if args.command == "rescan":
            load_saved(directory, home=args.settings_home)
            atomic_write_bytes(directory / "fleet-rescan.request", b"inventory requested\n")
            return out.finish(message="Requested one local inventory refresh; the running peer will perform it.")
        if args.command == "transports":
            return command_transports(args, directory, out)
        if args.command == "baskets":
            return command_baskets(args, directory, out)
        if args.command == "recovery":
            return command_recovery(args, directory, out, approval)
        if args.command == "git-client":
            from Special._sync.git_client import discover_clients, LABELS, validate_choice

            config = load_saved(directory, home=args.settings_home)
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
                save_saved(directory, config, home=args.settings_home)
                return out.finish(message=f"Selected {LABELS[args.client]}. Resume the peer to use its "
                                          "desktop shortcut.")
            if args.disable:
                config["git_client"] = None
                save_saved(directory, config, home=args.settings_home)
                return out.finish(message="Desktop shortcut turned off.")
            out.data(selected=config.get("git_client"), detected=discover_clients(config.get("git_client")))
            return out.finish(rows=True)
        if args.command == "setup":
            return guided_fleet_setup(directory, home=args.settings_home)
        if args.command == "leave":
            return command_leave(directory, out, approval, home=args.settings_home)
        if args.command == "join":
            plan = _peer_plan(args)
            if not approval.decide(plan, lambda: _cli.outline("Start this machine as a fleet peer", plan),
                                   question="Look through these folders once and start sharing?"):
                return approval.code
            config = configure(args, directory)
            if args.configure_only:
                return out.finish(message="Saved. Start sharing with gitso peer run, or the tray.")
        else:
            config = load_saved(directory, home=args.settings_home)
        if args.command == "doctor":
            return command_doctor(config, out)
        if args.command == "key":
            from Special._runtime.output import fleet_key_record
            out.data(**fleet_key_record(config["fleet_secret"], show=args.show))
            return out.finish(rows=True)
        if args.command == "safe-to-wipe":
            return command_safe_to_wipe(config, out)

        if stopping is None:
            stopping = threading.Event()
            for signal_name in ("SIGINT", "SIGTERM"):
                signal.signal(getattr(signal, signal_name), lambda *_: stopping.set())
        return run_peer(config, directory, stopping, on_ready=on_ready,
                        settings_home=args.settings_home, serve=serve)
    except (OSError, ValueError, KeyError, GhError, EOFError) as exc:
        return _cli.fail(args, name, f"{exc}.")


def main(argv=None, stopping=None, on_ready=None, serve=None):
    enable_unicode_output()  # before argparse, which may print and exit on --help
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    name = _command_name(args)
    if args.command == "preflight":
        return _main(argv, stopping, on_ready)
    try:
        args.config_dir = fleet_directory(args.config_dir, home=args.settings_home)
        load_fleet_settings(args.settings_home)  # invalid common settings fail before locks/effects
    except (OSError, ValueError) as exc:
        return _cli.fail(args, name, f"{exc}.")
    if args.command == "start-at-sign-in":
        try:
            return run_autostart(args, _cli.Out(args, name, PAGES["start-at-sign-in"]))
        except (OSError, ValueError) as exc:
            return _cli.fail(args, name, f"{exc}.")
    if args.command == "setup" and not args.configure_only:
        # Setup ends with the app running where you can see it -- a tray icon on Windows -- not
        # a terminal you have to keep open. The lock is released before the tray starts, because
        # the tray's own worker takes it for the running peer.
        directory = args.config_dir.expanduser()
        try:
            with app_lock(directory):
                code = _main(argv)
        except (OSError, ValueError) as exc:
            return _cli.fail(args, name, f"{exc}.")
        if code:
            return code
        offer_start_at_login(profile_arguments(directory, args.settings_home))
        _say("Setup is complete. Start gitSpecOps with the tray and web view: gitso tray; "
             "the web view without a tray: gitso serve-web; headless: gitso peer run.")
        return 0
    if args.command in ("doctor", "rescan", "preflight", "key", "status"):
        return _main(argv, stopping, on_ready)
    try:
        with app_lock(args.config_dir.expanduser()):
            return _main(argv, stopping, on_ready, serve)
    except (OSError, ValueError) as exc:
        return _cli.fail(args, name, f"{exc}.")


if __name__ == "__main__":
    raise SystemExit(main())
