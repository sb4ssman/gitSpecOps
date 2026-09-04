"""Persistent local Sync Suggester state: configuration and the local-only catalog.

Two files live side by side in one OS-appropriate directory:

    config.json     machine identity, registered roots, state dir, freshness thresholds
    catalog.json    LOCAL ONLY — repo_id -> readable name, local path, optional alias

`config.json` is local too, but the catalog is the privacy pressure point: it is the file
that maps a synced manifest's opaque `repo_id` back to a human name and a path on this
disk. It is never written into the transport's state directory and never leaves the
machine. See `manifest.py` for the synced-side boundary.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from pathlib import Path

from folder_transport import SAFE_MACHINE_ID, atomic_write_bytes
from manifest import is_fleet_secret, new_fleet_secret
from repo_transport import SAFE_REPO_SPEC

CONFIG_SCHEMA_VERSION = 1
CATALOG_SCHEMA_VERSION = 1
CONFIG_NAME = "config.json"
CATALOG_NAME = "catalog.json"

DEFAULT_STALE_HOURS = 24
DEFAULT_EXPIRED_DAYS = 7

CONFIG_KEYS = frozenset({
    "schema_version", "fleet_secret", "machine_id", "machine_label", "state_dir",
    "state_repo", "roots", "stale_hours", "expired_days",
})
ROOT_KEYS = frozenset({"path", "recursive"})


def default_config_dir() -> Path:
    """Where local state lives. `GITSPECOPS_SYNC_HOME` overrides everything."""
    override = os.environ.get("GITSPECOPS_SYNC_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or "~/AppData/Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "gitspecops" / "sync-suggester"


def config_path(config_dir: Path) -> Path:
    return Path(config_dir) / CONFIG_NAME


def catalog_path(config_dir: Path) -> Path:
    return Path(config_dir) / CATALOG_NAME


def default_machine_id() -> str:
    """A stable, non-personal-looking id derived from the hostname."""
    raw = socket.gethostname().split(".")[0] or "machine"
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", raw).strip("-._")
    return cleaned[:80] if SAFE_MACHINE_ID.fullmatch(cleaned[:80] or "x") else "machine"


def default_config(machine_id: str | None = None, fleet_secret: str | None = None) -> dict:
    """A fresh config. Generates a new fleet secret unless joining an existing fleet."""
    resolved = machine_id or default_machine_id()
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        # Never written into the transport: a state folder that also carried the secret would
        # protect nothing. It reaches other machines by the user, out of band.
        "fleet_secret": fleet_secret or new_fleet_secret(),
        "machine_id": resolved,
        "machine_label": resolved,
        "state_dir": None,
        # Exactly one transport at a time: a folder your sync client replicates, or a
        # private repository addressed through `gh`. Never both — two places to publish
        # means two disagreeing sources of truth.
        "state_repo": None,
        "roots": [],
        "stale_hours": DEFAULT_STALE_HOURS,
        "expired_days": DEFAULT_EXPIRED_DAYS,
    }


def validate_config(value: object) -> dict:
    """Reject anything the rest of the tool would have to guess about."""
    if not isinstance(value, dict):
        raise ValueError("config must be a JSON object")
    extra = set(value) - CONFIG_KEYS
    if extra:
        raise ValueError(f"config has unknown fields: {sorted(extra)}")
    if value.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ValueError(f"unsupported config schema_version: {value.get('schema_version')!r}")
    if not is_fleet_secret(value.get("fleet_secret")):
        raise ValueError("fleet_secret must be 64 hexadecimal characters")
    machine_id = value.get("machine_id")
    if not isinstance(machine_id, str) or not SAFE_MACHINE_ID.fullmatch(machine_id):
        raise ValueError("machine_id may contain only letters, digits, dot, underscore, and dash")
    if not isinstance(value.get("machine_label"), str) or not value["machine_label"]:
        raise ValueError("machine_label must be a non-empty string")
    state_dir = value.get("state_dir")
    if state_dir is not None and (not isinstance(state_dir, str) or not state_dir):
        raise ValueError("state_dir must be a non-empty string or null")
    state_repo = value.get("state_repo")
    if state_repo is not None:
        if not isinstance(state_repo, str) or not SAFE_REPO_SPEC.fullmatch(state_repo):
            raise ValueError("state_repo must look like owner/name, or be null")
    if state_dir and state_repo:
        raise ValueError("set either state_dir or state_repo, not both")
    roots = value.get("roots")
    if not isinstance(roots, list):
        raise ValueError("roots must be a list")
    seen: set[str] = set()
    for index, root in enumerate(roots):
        if not isinstance(root, dict):
            raise ValueError(f"roots[{index}] must be an object")
        unknown = set(root) - ROOT_KEYS
        if unknown:
            raise ValueError(f"roots[{index}] has unknown fields: {sorted(unknown)}")
        path = root.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"roots[{index}].path must be a non-empty string")
        if not isinstance(root.get("recursive", False), bool):
            raise ValueError(f"roots[{index}].recursive must be a boolean")
        key = str(Path(path).expanduser())
        if key in seen:
            raise ValueError(f"duplicate root: {path}")
        seen.add(key)
    for key, low in (("stale_hours", 1), ("expired_days", 1)):
        number = value.get(key)
        if not isinstance(number, int) or isinstance(number, bool) or number < low:
            raise ValueError(f"{key} must be an integer >= {low}")
    if value["expired_days"] * 24 < value["stale_hours"]:
        raise ValueError("expired_days must not be shorter than stale_hours")
    return value


def load_config(config_dir: Path | None = None) -> dict | None:
    """Return the saved config, or None when this machine has never run `init`."""
    path = config_path(config_dir or default_config_dir())
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    return validate_config(value)


def save_config(config_dir: Path, config: dict) -> Path:
    validate_config(config)
    path = config_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return path


def load_catalog(config_dir: Path | None = None) -> dict[str, dict]:
    """Local-only repo_id -> {display_name, path, alias}. Missing/corrupt reads as empty.

    Entries are keyed by the fleet-salted repo_id, so changing the fleet secret orphans the
    old keys. They are harmless (nothing joins to them any more) and re-observation repopulates
    the new ones; `prune_catalog` clears them out when the user wants a tidy file.
    """
    path = catalog_path(config_dir or default_config_dir())
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != CATALOG_SCHEMA_VERSION:
        return {}
    entries = value.get("repositories")
    if not isinstance(entries, dict):
        return {}
    return {
        repo_id: entry for repo_id, entry in entries.items()
        if isinstance(repo_id, str) and isinstance(entry, dict)
    }


def save_catalog(config_dir: Path, catalog: dict[str, dict]) -> Path:
    path = catalog_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": CATALOG_SCHEMA_VERSION, "repositories": catalog}
    atomic_write_bytes(path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return path


def merge_catalog(existing: dict[str, dict], observed: dict[str, dict]) -> dict[str, dict]:
    """Fold a fresh observation into the saved catalog, keeping user-supplied aliases.

    Observation wins for facts it just measured (name, path); the alias is only ever set by
    the user, so it survives every re-observation. Entries for repositories not seen this
    run are kept — a repo that is merely on another machine today is still worth naming.
    """
    merged = {repo_id: dict(entry) for repo_id, entry in existing.items()}
    for repo_id, entry in observed.items():
        record = merged.setdefault(repo_id, {})
        alias = record.get("alias")
        record.update(entry)
        if alias:
            record["alias"] = alias
    return merged


def display_name_for(repo_id: str, catalog: dict[str, dict]) -> str:
    """Readable name for a repo_id, falling back to a short stable identifier."""
    entry = catalog.get(repo_id) or {}
    return entry.get("alias") or entry.get("display_name") or f"repo:{repo_id[:8]}"


def roots_from_archive_registry(repo_root: Path) -> list[str]:
    """Registered archive roots from Archive Updater's local registry, if it exists."""
    registry = Path(repo_root) / "git-archive-updater" / "managed_archives.json"
    if not registry.is_file():
        return []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    installations = data.get("installations")
    if not isinstance(installations, list):
        return []
    roots = []
    for item in installations:
        if isinstance(item, dict) and isinstance(item.get("root"), str) and item["root"]:
            roots.append(item["root"])
    return roots


def prune_catalog(catalog: dict[str, dict], keep: set[str]) -> dict[str, dict]:
    """Drop catalog entries no longer reachable, e.g. after a fleet-secret change."""
    return {repo_id: entry for repo_id, entry in catalog.items() if repo_id in keep}
