"""Fleet app configuration: schema v3, the peer model.

v2 had two kinds of machine — a `host` that owned the database and served the dashboard, and
`connect` clients that pushed reports to it. That asymmetry was the design mistake: when the
host was off, clients had nowhere to publish and nobody had a dashboard.

v3 has one kind of machine: a **peer**. Every peer observes itself, publishes its own manifest
to every transport it has, serves its own dashboard on loopback, and — when Tailscale happens to
be up — answers other peers and pulls from them. No machine is in charge of another, and no
transport is a precondition for any other.

Transports are a dict rather than flat keys because they are complements, not alternatives:
a peer is expected to have several, and adding a fourth should not mean four more top-level keys.
"""
from __future__ import annotations

from pathlib import Path

from manifest import is_fleet_secret

APP_CONFIG = "fleet-app.json"
CONFIG_VERSION = 3
DEFAULT_LOCAL_PORT = 8760
DEFAULT_TAILNET_PORT = 8765
DEFAULT_FOLDER_SECONDS = 300
DEFAULT_REPO_SECONDS = 1800


def migrate(config: dict) -> dict:
    """v1 -> v2 -> v3. A saved configuration is never silently discarded."""
    if config.get("version") == 1:
        config = dict(config)
        config["version"] = 2
        config["inventory_notice_acknowledged"] = bool(
            config.pop("scan_notice_acknowledged", False))
        config["observation_mode"] = "filesystem-events"
        config["debounce_seconds"] = 0.75
        config.pop("interval", None)
    if config.get("version") == 2:
        config = dict(config)
        was_host = config.get("mode") == "host"
        transports = {}
        if config.get("replica_folder"):
            transports["folder"] = {"path": config["replica_folder"],
                                    "seconds": int(config.get("folder_seconds")
                                                   or DEFAULT_FOLDER_SECONDS)}
        if config.get("replica_repo"):
            transports["repo"] = {"name": config["replica_repo"],
                                  "seconds": int(config.get("github_seconds")
                                                 or DEFAULT_REPO_SECONDS)}
        # Both old modes used the tailnet, so both keep it — as one transport among several
        # rather than as the thing the machine's identity depended on. `allowed_login` is
        # resolved at startup for a former client, which never stored one.
        transports["tailnet"] = {
            "port": int(config.get("port") or DEFAULT_TAILNET_PORT) if was_host
            else DEFAULT_TAILNET_PORT,
            "allowed_login": config.get("allowed_login"),
        }
        for key in ("replica_folder", "folder_seconds", "replica_repo", "github_seconds",
                    "port", "allowed_login", "server"):
            config.pop(key, None)
        config.update(version=3, mode="peer", transports=transports,
                      local_port=int(config.get("local_port") or DEFAULT_LOCAL_PORT))
    return config


def validate(config: dict) -> dict:
    if config.get("version") != CONFIG_VERSION or config.get("mode") != "peer":
        raise ValueError("unsupported fleet app configuration")
    if not is_fleet_secret(config.get("fleet_secret")):
        raise ValueError("invalid fleet identity")
    if not config.get("machine_id"):
        raise ValueError("this machine has no stable id")
    if config.get("inventory_notice_acknowledged") is not True:
        raise ValueError("initial inventory discovery has not been acknowledged")
    if config.get("observation_mode") != "filesystem-events":
        raise ValueError("unsupported observation mode")
    if not config.get("roots") or any(not Path(p).is_dir() for p in config["roots"]):
        raise ValueError("every configured repository root must exist")
    heartbeat = config.get("heartbeat")
    if type(heartbeat) is not int or heartbeat < 1:
        raise ValueError("heartbeat must be a positive number of seconds")
    if heartbeat > 60:
        raise ValueError("live heartbeat must be <= 60 seconds (stale threshold is 120 seconds)")
    debounce = config.get("debounce_seconds")
    if not isinstance(debounce, (int, float)) or isinstance(debounce, bool) or debounce < 0:
        raise ValueError("debounce_seconds must be zero or greater")
    if not 1024 <= int(config.get("local_port") or 0) <= 65535:
        raise ValueError("local_port must be between 1024 and 65535")

    transports = config.get("transports")
    if not isinstance(transports, dict):
        raise ValueError("transports must be an object")
    for name, entry in transports.items():
        if name not in ("folder", "repo", "tailnet"):
            raise ValueError(f"unknown transport {name!r}")
        if not isinstance(entry, dict):
            raise ValueError(f"transport {name!r} must be an object")
    folder = transports.get("folder")
    if folder:
        if not Path(folder.get("path", "")).is_dir():
            raise ValueError("the folder transport must point at an existing directory")
        if int(folder.get("seconds", 0)) < 1:
            raise ValueError("folder transport interval must be positive")
    repo = transports.get("repo")
    if repo:
        if not repo.get("name"):
            raise ValueError("the repo transport needs an owner/name")
        if int(repo.get("seconds", 0)) < 1:
            raise ValueError("repo transport interval must be positive")
    tailnet = transports.get("tailnet")
    if tailnet and not 1024 <= int(tailnet.get("port") or 0) <= 65535:
        raise ValueError("tailnet port must be between 1024 and 65535")
    # A peer with no transports is still legitimate: it observes itself and shows its own
    # dashboard. That is a useful single-machine tool, and refusing it would make the fleet
    # features a precondition for the basic ones.
    return config


def new_config(machine_id: str, label: str, roots, fleet_secret: str, *,
               debounce_seconds: float = 0.75, local_port: int = DEFAULT_LOCAL_PORT,
               transports: dict | None = None) -> dict:
    return {
        "version": CONFIG_VERSION, "mode": "peer",
        "machine_id": machine_id, "label": label,
        "fleet_secret": fleet_secret,
        "roots": [str(Path(root).expanduser().resolve()) for root in roots],
        "observation_mode": "filesystem-events",
        "debounce_seconds": debounce_seconds,
        "heartbeat": 30,
        "inventory_notice_acknowledged": True,
        "local_port": int(local_port),
        "transports": transports or {},
    }


def describe(config: dict) -> str:
    """One human line per configured transport, for setup output and `doctor`."""
    transports = config.get("transports") or {}
    lines = []
    folder = transports.get("folder")
    if folder:
        lines.append(f"  folder   {folder['path']} every {folder['seconds']}s")
    repo = transports.get("repo")
    if repo:
        lines.append(f"  repo     {repo['name']} every {repo['seconds']}s")
    tailnet = transports.get("tailnet")
    if tailnet:
        lines.append(f"  tailnet  port {tailnet['port']} (peers pull from each other)")
    if not lines:
        lines.append("  (none — this peer observes itself and shows its own dashboard)")
    return "\n".join(lines)
