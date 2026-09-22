"""The archive registry: which archive folders `archive_manage` looks after, and how each last ran.

Per-user state, in `Basic/_paths.config_home()` -- never in the checkout, so a checkout can be
moved, re-cloned or deleted without losing it, and it can never be committed by accident. The
file is named `gitspecops_managed_archives.json` so it is recognizable on its own.

Written atomically. A registry that exists but cannot be read is an error to show, not an
empty registry to silently overwrite; readers that only want a hint (`registered_roots`) are
the exception, and say so.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from Basic._files import atomic_write_bytes
from Basic._paths import config_home

REGISTRY_NAME = "gitspecops_managed_archives.json"


def registry_path() -> Path:
    return config_home() / REGISTRY_NAME


@dataclass
class InstallRecord:
    root: str
    installed_at: str
    updated_at: str
    git_spec_ops_dir: str
    python_executable: str
    runner: str
    launcher: str
    launcher_type: str
    repo_count: int
    approved_remote_prefixes: list[str]
    mode: str = "update"


def load_registry(path: Path | None = None) -> dict:
    """The registry, or an empty one when the file does not exist yet. Raises if it is unreadable."""
    path = path or registry_path()
    if not path.exists():
        return {"version": 1, "installations": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("version", 1)
    data.setdefault("installations", [])
    return data


def save_registry(data: dict, path: Path | None = None) -> Path:
    path = path or registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_bytes(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))


def upsert_record(record: InstallRecord, path: Path | None = None) -> None:
    """Add or replace the entry for record.root, keeping its original install time."""
    data = load_registry(path)
    installations = data["installations"]
    payload = asdict(record)
    for index, item in enumerate(installations):
        if Path(item["root"]).resolve() == Path(record.root).resolve():
            payload["installed_at"] = item.get("installed_at", record.installed_at)
            installations[index] = payload
            break
    else:
        installations.append(payload)
    save_registry(data, path)


def forget_installation(root: Path, path: Path | None = None) -> bool:
    """Drop one archive from the registry. Touches nothing in the archive folder itself."""
    data = load_registry(path)
    resolved = Path(root).resolve()
    kept = [item for item in data["installations"] if Path(item["root"]).resolve() != resolved]
    if len(kept) == len(data["installations"]):
        return False
    data["installations"] = kept
    save_registry(data, path)
    return True


def registered_roots(path: Path | None = None) -> list[str]:
    """Registered archive roots, for other tools that want a hint. Never raises: a missing or
    unreadable registry simply offers nothing."""
    path = path or registry_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    installations = data.get("installations") if isinstance(data, dict) else None
    if not isinstance(installations, list):
        return []
    return [item["root"] for item in installations
            if isinstance(item, dict) and isinstance(item.get("root"), str) and item["root"]]
