"""The whole setup picture and the fleet steps, without prompts.

Why:          setup must look and work the same in the terminal, the app's setup page and an
              agent's hands. This is the one source: what is set up, what each next tier needs
              and unlocks, and the join/leave steps as plain function calls.
Reads:        the settings profile; tool readiness (Git, a gh login, Tailscale, likely sync
              folders, the web view's port) only when asked to.
May change:   join and leave only: the fleet key (while nothing is shared under it) and which
              transports are selected. Libraries are the machine's (Special/machine.py).
Results:      plain dicts, JSON-ready.
Layer:        Elaborate: other machines, or over time.
Status:       working
"""
from __future__ import annotations

from pathlib import Path

#: The growth matrix. Each tier multiplies what the ones before it reach. `built` is honest:
#: False marks what the product promises but has not built yet.
TIERS = (
    {"id": "installed", "title": "Installed", "needs": "nothing", "unlocks": [
        ("See and check any folder you name", True),
        ("Fetch and safe fast-forward, on request", True),
        ("Scans, checked commit and push, history cleanup", True),
        ("Agents can work on folders you name", True)]},
    {"id": "machine", "title": "This machine", "needs": "your library folders", "unlocks": [
        ("An always-on view and a map of this machine", True),
        ("Security findings on the map, on request", True),
        ("Recovery snapshots of unfinished work", True),
        ("Keep repositories current automatically, with your consent", False),
        ("Agents can work on this machine", True)]},
    {"id": "fleet", "title": "A fleet", "needs": "a fleet key and a way to share", "unlocks": [
        ("Every machine on one map", True),
        ("Know where work is unpushed; clone what is missing", True),
        ("Prove a machine safe to wipe from copies elsewhere", True),
        ("Audit every machine's repositories", False),
        ("Agents can observe the whole fleet", True)]},
    {"id": "managed_repo", "title": "A managed repository", "needs":
        "a private GitHub repository that gitSpecOps manages (needs a gh login)", "unlocks": [
        ("Machines that are switched off still appear", True),
        ("One privacy policy on every machine", False),
        ("Ask another machine to act; it does when it next wakes", False),
        ("Agents can queue work for any machine", False)]},
    {"id": "tailnet", "title": "Tailscale", "needs": "your own tailnet", "unlocks": [
        ("Live status between machines", True),
        ("Watch the web view from your phone, and run its previews", True),
        ("Ask live, approve, and watch it happen", False)]},
)


def _profile(home, config_dir):
    from Special._settings.fleet import fleet_directory, load_fleet_settings

    return load_fleet_settings(home), fleet_directory(config_dir, home=home)


# --------------------------------------------------------------------------- fleets by name
# People find and join a fleet by its name on their own tailnet ("Home-Fleet"), not by
# copying a key (the user, 2026-11-16: a pasted key failed twice). The key still exists, as a
# background detail: it salts repository ids for the synced folder and the state repository and
# seals shared values. A machine already in the fleet hands it over to a joining machine of the
# same Tailscale user (GET /v1/session); nobody copies it unless a machine has no Tailscale.

DEFAULT_FLEET_NAME = "My fleet"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fleet_name(config) -> str | None:
    named = (config or {}).get("fleet_name")
    return named.get("name") if isinstance(named, dict) else None


def name_fleet(home=None, config_dir=None, *, name: str, at: str | None = None) -> dict:
    """Give this machine's fleet a name. `at` (when the name was given) lets the newest name win
    when machines compare (Elaborate/_fleet/peer.py)."""
    from Elaborate._fleet.cli import load_saved, save_saved
    name = " ".join(str(name or "").split())
    if not name or len(name) > 60 or not name.isprintable():
        raise ValueError("a fleet name is 1 to 60 ordinary characters")
    _snapshot, directory = _profile(home, config_dir)
    config = load_saved(directory, home=home)
    config["fleet_name"] = {"name": name, "at": at or _now()}
    save_saved(directory, config, home=home)
    return config["fleet_name"]


def fleets_on_tailnet(port: int = 8765) -> list[dict]:
    """The fleets your own machines on this tailnet are in, by name: [{fleet_id, name, machines}].
    Only machines running the app with Tailscale on answer; each says only its fleet's name and id."""
    from Elaborate._fleet.net import FleetClient, discover_hosts
    fleets: dict = {}
    for host in discover_hosts(port=port):
        if not host.get("serving"):
            continue
        try:
            about = FleetClient(host["url"]).request("/v1/fleet")
        except (OSError, ValueError):
            continue
        if not isinstance(about, dict) or not isinstance(about.get("fleet_id"), str):
            continue
        entry = fleets.setdefault(about["fleet_id"], {"fleet_id": about["fleet_id"], "name": None, "at": "",
                                                      "machines": []})
        entry["machines"].append(host["label"])
        named = about.get("fleet_name") if isinstance(about.get("fleet_name"), dict) else {}
        if named.get("name") and str(named.get("at", "")) >= entry["at"]:
            entry["name"], entry["at"] = str(named["name"])[:60], str(named.get("at", ""))
    return [{"fleet_id": f["fleet_id"], "name": f["name"] or f"Unnamed fleet {f['fleet_id'][:6]}",
             "machines": sorted(f["machines"], key=str.casefold)} for f in fleets.values()]


def key_from_fleet(fleet_id: str, port: int = 8765) -> tuple[str, dict | None]:
    """(fleet key, fleet name) handed over by a running machine of fleet `fleet_id` on this
    tailnet, which checks that the asking device is its own user's."""
    from Elaborate._fleet.net import FleetClient, discover_hosts
    from Special._sync.manifest import fleet_id_for, is_fleet_secret
    for host in discover_hosts(port=port):
        if not host.get("serving"):
            continue
        try:
            session = FleetClient(host["url"]).request("/v1/session")
        except (OSError, ValueError):
            continue
        secret = session.get("fleet_secret") if isinstance(session, dict) else None
        if is_fleet_secret(secret) and fleet_id_for(secret) == fleet_id:
            named = session.get("fleet_name")
            return secret, named if isinstance(named, dict) else None
    raise ValueError("no machine of that fleet is answering on Tailscale right now; start its app")


def setup_state(home=None, config_dir=None, *, readiness: bool = False) -> dict:
    """Everything a setup screen or an agent needs, in one document."""
    from Special._sync.enrollment import DEFAULT_PRESENTATION
    from Special._sync.manifest import fleet_id_for

    snapshot, directory = _profile(home, config_dir)
    config = snapshot.config("app") if snapshot is not None else None
    transports = dict((config or {}).get("transports") or {})
    reached = {"installed": True, "machine": config is not None,
               "fleet": bool(transports), "managed_repo": "repo" in transports,
               "tailnet": "tailnet" in transports}
    state = {
        "profile": {"exists": snapshot is not None},
        "machine": None if config is None else {
            "id": config["machine_id"], "label": config["label"], "libraries": list(config["roots"]),
            "presentation": {**DEFAULT_PRESENTATION, **(config.get("presentation") or {})},
            "local_port": int(config["local_port"])},
        "fleet": None if not transports else {
            "fleet_id": fleet_id_for(config["fleet_secret"]), "name": fleet_name(config),
            "share_names": config.get("share_names", True),
            "transports": {name: {key: value for key, value in entry.items() if key != "allowed_login"}
                           for name, entry in transports.items()}},
        "tiers": [{"id": tier["id"], "title": tier["title"], "needs": tier["needs"],
                   "reached": reached[tier["id"]],
                   "unlocks": [{"text": text, "built": built} for text, built in tier["unlocks"]]}
                  for tier in TIERS],
    }
    state["next"] = next((tier["id"] for tier in state["tiers"] if not tier["reached"]), None)
    if readiness:
        from Elaborate._fleet.cli import preflight_state

        ready = preflight_state(int(config["local_port"]) if config else 8760)
        state["readiness"] = {**ready, "folders": [str(folder) for folder in ready["folders"]]}
    return state


def apply_transports(config, *, folder=None, clear_folder=False, folder_seconds=None,
                     repo=None, create_repo=False, clear_repo=False, repo_seconds=None,
                     tailnet=False, clear_tailnet=False, tailnet_port=None, directory=None, home=None,
                     names=None, tailnet_seconds=None):
    """Change which transports this machine shares through, and save. The terminal's
    `transports` command and the setup page both come here. `names`: per connection, whether
    it carries readable names; a connection re-set without one keeps the choice it had."""
    from Elaborate._fleet.cli import require_gh, save_saved
    from Elaborate._fleet.config import (DEFAULT_FOLDER_SECONDS, DEFAULT_REPO_SECONDS,
                                         DEFAULT_TAILNET_PORT, validate)
    from Elaborate._transport.repo import RepoTransport, create_state_repo

    transports = dict(config.get("transports") or {})
    kept = {name: entry["names"] for name, entry in transports.items() if "names" in entry}
    if folder and clear_folder:
        raise ValueError("choose a folder or clearing it, not both")
    if repo and clear_repo:
        raise ValueError("choose a repository or clearing it, not both")
    if folder:
        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("the synced folder must already exist")
        transports["folder"] = {"path": str(path), "seconds": folder_seconds or DEFAULT_FOLDER_SECONDS}
    elif clear_folder:
        transports.pop("folder", None)
    elif folder_seconds and transports.get("folder"):
        transports["folder"]["seconds"] = folder_seconds
    if repo:
        transports["repo"] = {"name": repo, "seconds": repo_seconds or DEFAULT_REPO_SECONDS}
    elif clear_repo:
        transports.pop("repo", None)
    elif repo_seconds and transports.get("repo"):
        transports["repo"]["seconds"] = repo_seconds
    if tailnet:
        previous = transports.get("tailnet") or {}
        transports["tailnet"] = {"port": tailnet_port or previous.get("port") or DEFAULT_TAILNET_PORT,
                                 "allowed_login": previous.get("allowed_login"),
                                 **({"seconds": previous["seconds"]} if "seconds" in previous else {})}
    elif clear_tailnet:
        transports.pop("tailnet", None)
    elif tailnet_port and transports.get("tailnet"):
        transports["tailnet"]["port"] = tailnet_port
    if tailnet_seconds and transports.get("tailnet"):
        transports["tailnet"]["seconds"] = int(tailnet_seconds)
    for name, value in {**kept, **(names or {})}.items():
        if name in transports:
            transports[name] = {**transports[name], "names": bool(value)}
    config["transports"] = transports
    validate(config)
    if hasattr(config, "snapshot"):
        config.snapshot.transport_changes("app", transports)
        config.snapshot.verify()
    if repo:
        require_gh()
        transport = RepoTransport(repo)
        health = transport.doctor()
        if not health.get("exists") and create_repo:
            create_state_repo(repo)
            health = transport.doctor()
        if not health.get("exists") or not health.get("private") or not health.get("permissions"):
            raise ValueError("the state repository must exist, be private and be writable; "
                             "allow creating it to have gitSpecOps make it")
    save_saved(directory, config, home=home)
    return config


def join_fleet(home=None, config_dir=None, *, key=None, folder=None, tailnet=False, repo=None,
               create_repo=False, share_names=None, names=None, tailnet_seconds=None,
               name: str | None = None, named_at: str | None = None) -> dict:
    """Join this enrolled machine to a fleet: an existing key, or a new fleet of its own; then any
    combination of transports. Returns the new setup state."""
    from Elaborate._fleet.cli import load_saved, save_saved
    from Special._settings.fleet import replace_fleet_secret
    from Special._sync.manifest import is_fleet_secret

    snapshot, directory = _profile(home, config_dir)
    config = snapshot.config("app") if snapshot is not None else None
    if config is None:
        raise ValueError("this machine is not enrolled; add a library folder first")
    if key:
        if not is_fleet_secret(key):
            raise ValueError("a fleet key is 64 hexadecimal characters")
        if key.lower() != config["fleet_secret"].lower():
            replace_fleet_secret(key, home=home, snapshot=snapshot)
    if not (folder or tailnet or repo):
        raise ValueError("choose at least one way to share: a synced folder, a managed repository or Tailscale")
    config = load_saved(directory, home=home)
    apply_transports(config, folder=folder, tailnet=tailnet, repo=repo, create_repo=create_repo,
                     directory=directory, home=home, names=names, tailnet_seconds=tailnet_seconds)
    if share_names is not None:
        config = load_saved(directory, home=home)
        config["share_names"] = bool(share_names)
        save_saved(directory, config, home=home)
    if name or not fleet_name(load_saved(directory, home=home)):
        # Unnamed: a placeholder dated as early as possible, so the fleet's real name wins as
        # soon as another machine says it.
        name_fleet(home, config_dir, name=name or DEFAULT_FLEET_NAME,
                   at=named_at or (None if name else "1970-01-01T00:00:00+00:00"))
    return setup_state(home, config_dir)


def leave_fleet(home=None, config_dir=None) -> dict:
    """Deselect every transport; the machine keeps its libraries and web view."""
    from Elaborate._fleet.cli import load_saved, save_saved

    snapshot, directory = _profile(home, config_dir)
    config = load_saved(directory, home=home)
    if config.get("transports"):
        config["transports"] = {}
        save_saved(directory, config, home=home)
    return setup_state(home, config_dir)
