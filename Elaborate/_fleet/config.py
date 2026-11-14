"""Fleet app configuration: schema v5, the peer model with baskets and recovery.

v2 had two kinds of machine — a `host` that owned the database and served the dashboard, and
`connect` clients that pushed reports to it. That asymmetry was the design mistake: when the
host was off, clients had nowhere to publish and nobody had a dashboard.

v3 has one kind of machine: a **peer**. Every peer observes itself, publishes its own manifest
to every transport it has, serves its own dashboard on loopback, and — when Tailscale happens to
be up — answers other peers and pulls from them. No machine is in charge of another, and no
transport is a precondition for any other.

Transports are a dict rather than flat keys because they are complements, not alternatives:
a peer is expected to have several, and adding a fourth should not mean four more top-level keys.

v4 adds `baskets`: per-scope repository selection (see `baskets.py`). Roots remain the
filesystem boundary; baskets narrow what is observed, published and captured *within* it. The
v3 defaults are "all" for observe and publish, so migrating changes no behavior.

v5 adds a separately confirmed recovery location and local-only repository policies. Recovery
never inherits the status transport: snapshots contain source content and filenames.

The v5 runtime shape is also projected from common settings by Special._settings.fleet.
save_saved/save_client_choice persist to that profile. No enrollment or I/O occurs on import.
"""
from __future__ import annotations

import copy
from pathlib import Path

import Special._sync.baskets as baskets
from Special._sync.manifest import is_fleet_secret
from Special._sync.git_client import validate_choice
from Elaborate._recovery.capture import CapturePolicy, CaptureRefused
from Elaborate._recovery.snapshot_store import REPO_ID, StoreRefused, validate_location
from Special._settings.fleet import (FleetConfig, load_fleet_settings,
                                    save_fleet_config)

# The record and its defaults are the machine enrollment's (Special); the fleet adds transports.
from Special._sync.enrollment import (CONFIG_VERSION, DEFAULT_FETCH_MINUTES,  # noqa: E402,F401
                                      DEFAULT_LOCAL_PORT, new_config)

DEFAULT_TAILNET_PORT = 8765
DEFAULT_FOLDER_SECONDS = 300
DEFAULT_REPO_SECONDS = 1800


def save_saved(directory: Path, config: dict, *, home=None, snapshot=None):
    """Save explicit app choices to the settings profile."""
    validate(config)
    if load_fleet_settings(home) is None and not isinstance(config, FleetConfig) and snapshot is None:
        raise ValueError("this machine has no settings profile; enroll it with: gitso enroll-machine add <library folder>")
    return save_fleet_config(config, component="app", home=home, snapshot=snapshot)


def save_client_choice(directory: Path, config: dict, choice):
    """Persist only this UI choice; runtime-discovered identity must not become preferences."""
    if isinstance(config, FleetConfig):
        updated = FleetConfig(config.original, config.snapshot, "app")
        home = config.snapshot.home
    else:
        updated, home = copy.deepcopy(config), None
    updated["git_client"] = choice
    save_saved(directory, updated, home=home)
    if isinstance(config, FleetConfig):
        config.snapshot, config.original = updated.snapshot, updated.original
    config["git_client"] = choice


def validate(config: dict) -> dict:
    validate_choice(config.get("git_client"))
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
    scopes = baskets.validate_scopes(config.get("baskets"))
    recovery = config.get("recovery")
    if not isinstance(recovery, dict) or set(recovery) != {"location", "confirmed", "policies"}:
        raise ValueError("recovery must define exactly location, confirmed, and policies")
    location, confirmed, policies = recovery["location"], recovery["confirmed"], recovery["policies"]
    if location is not None and (not isinstance(location, str) or not Path(location).is_dir()):
        raise ValueError("recovery location must be an existing directory or null")
    if not isinstance(policies, dict):
        raise ValueError("recovery policies must be an object")
    for repo_id, raw_policy in policies.items():
        if not REPO_ID.fullmatch(str(repo_id)):
            raise ValueError("recovery policy keys must be opaque repository ids")
        if not isinstance(raw_policy, dict) or set(raw_policy) != {
                "obey_gitignore", "secret_protection", "allow_paths"}:
            raise ValueError("each recovery policy must define ignore, secret protection, and paths")
        try:
            CapturePolicy(**raw_policy).validate()
        except (CaptureRefused, TypeError) as exc:
            raise ValueError(f"invalid recovery policy: {exc}") from None
    if location is not None and confirmed is not True:
        raise ValueError("recovery location has not been explicitly confirmed")
    if location is not None:
        status_folder = ((config.get("transports") or {}).get("folder") or {}).get("path")
        try:
            validate_location(location, status_folder=status_folder, roots=config["roots"])
        except StoreRefused as exc:
            raise ValueError(str(exc)) from None
    if scopes["capture"]["mode"] != "none" and (location is None or confirmed is not True):
        raise ValueError("a capture basket needs a separately confirmed recovery location")
    heartbeat = config.get("heartbeat")
    if type(heartbeat) is not int or heartbeat < 1:
        raise ValueError("heartbeat must be a positive number of seconds")
    if heartbeat > 60:
        raise ValueError("heartbeat must be 60 seconds or less")
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
    fetch_minutes = config.get("fetch_minutes", DEFAULT_FETCH_MINUTES)
    if type(fetch_minutes) is not int or fetch_minutes < 0:
        raise ValueError("fetch_minutes must be a whole number of minutes (0 turns fetching off)")
    if not isinstance(config.get("share_names", True), bool):
        raise ValueError("share_names must be true or false")
    # A peer with no transports is still legitimate: it observes itself and shows its own
    # dashboard. That is a useful single-machine tool, and refusing it would make the fleet
    # features a precondition for the basic ones.
    return config


def recovery_policy(config: dict, repo_id: str) -> CapturePolicy:
    """The local-only policy for one opaque repository id, safe by default."""
    raw = ((config.get("recovery") or {}).get("policies") or {}).get(repo_id)
    return CapturePolicy(**raw) if raw else CapturePolicy()


def policy_record(policy: CapturePolicy) -> dict:
    """JSON form kept in the local app config; do not sync this with fleet status."""
    policy.validate()
    return {"obey_gitignore": policy.obey_gitignore,
            "secret_protection": policy.secret_protection,
            "allow_paths": list(policy.allow_paths)}


# `git fetch` every observed repository on this interval, so "behind" is measured against the
# remote rather than against whenever someone last fetched by hand. 0 turns it off.


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
    if shares_names(config):
        lines.append("  names    shared: repository names, branches and current commits"
                     + (" (the synced folder's provider can read them too)" if folder else ""))
    else:
        lines.append("  names    withheld: other machines see salted ids only")
    return "\n".join(lines)


def shares_names(config: dict) -> bool:
    """Whether this machine publishes readable names (manifest v5). On unless turned off."""
    return config.get("share_names", True) is True
