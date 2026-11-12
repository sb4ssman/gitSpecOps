"""Enroll this machine with the app: its identity, its library folders, how the app shows itself.

Why:          the tray, the web view and every local command need to know which folders hold
              this machine's repositories, and nothing may be inventoried before the person
              names those folders. Joining a fleet is a separate, later step (Elaborate).
Reads:        the common settings profile. `find_libraries` reads folder names under the
              places it is told to look, only after its own confirmation (no Git, no contents).
May change:   the profile's machine identity and the app component's libraries and
              presentation. Never transports, keys of a fleet, or any repository.
Results:      plain records and plans for Special/enroll_machine.py and the fleet commands.
Layer:        Special: this machine, once.
Status:       working
"""
from __future__ import annotations

import copy
import os
import string
import sys
from pathlib import Path

from Basic._discovery import find_repos
from Special._settings import SettingsError
from Special._settings.fleet import fleet_home, load_fleet_settings, save_fleet_config
from Special._sync import baskets
from Special._sync.config import default_machine_id
from Special._sync.manifest import new_fleet_secret

CONFIG_VERSION = 5
DEFAULT_LOCAL_PORT = 8760
DEFAULT_FETCH_MINUTES = 15
#: The usual setup: double-clicking the tray opens the web view, served on this machine only.
DEFAULT_PRESENTATION = {"face": "web", "web": "loopback"}


def new_config(machine_id: str, label: str, roots, fleet_secret: str, *,
               debounce_seconds: float = 0.75, local_port: int = DEFAULT_LOCAL_PORT,
               transports: dict | None = None, scopes: dict | None = None,
               share_names: bool = True) -> dict:
    """The app's record for this machine. With no transports it is a machine-only enrollment."""
    return {
        "version": CONFIG_VERSION, "mode": "peer",
        "fetch_minutes": DEFAULT_FETCH_MINUTES,
        "share_names": share_names,
        "baskets": baskets.validate_scopes(scopes) if scopes
                   else copy.deepcopy(baskets.DEFAULT_SCOPES),
        "recovery": {"location": None, "confirmed": False, "policies": {}},
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


def inventory_notice(roots) -> str:
    """Exactly what enrolling these folders lets the app look at, said before it looks."""
    listed = "\n".join(f"  {Path(root).expanduser().resolve()}" for root in roots)
    return ("When the app next starts it inventories, once and recursively:\n" + listed + "\n"
            "It reads folder names to find Git repositories and each repository's Git status.\n"
            "It copies, sends and changes nothing. After that, file notifications check only a\n"
            "repository that changed. Nothing outside these folders is looked at.")


def _snapshot(home):
    snapshot = load_fleet_settings(home)
    if snapshot is None:
        raise ValueError(f"no settings profile at {fleet_home(home)}; create it with "
                         "setup_gitspecops.py first")
    return snapshot


def enrollment(home=None):
    """(machine, app record or None) for this profile; reading writes nothing."""
    snapshot = _snapshot(home)
    return snapshot.document.get("machine"), snapshot.config("app")


def _check_nesting(roots):
    resolved = [Path(root).resolve() for root in roots]
    for index, one in enumerate(resolved):
        for other in resolved[index + 1:]:
            if one == other or one in other.parents or other in one.parents:
                raise ValueError(f"libraries may not overlap: {one} and {other}")


def add_libraries(paths, *, home=None, label=None, local_port=None) -> list[str]:
    """Add library folders; the first one enrolls this machine. Returns the saved libraries."""
    paths = [Path(path).expanduser().resolve() for path in paths]
    missing = [str(path) for path in paths if not path.is_dir()]
    if missing:
        raise ValueError(f"not an existing folder: {', '.join(missing)}")
    snapshot = _snapshot(home)
    config = snapshot.config("app")
    if config is None:
        machine = snapshot.document.get("machine")
        machine_id = machine["id"] if machine else default_machine_id()
        secret = machine["fleet_secret"] if machine else new_fleet_secret()
        config = new_config(machine_id, label or (machine["label"] if machine else machine_id),
                            paths, secret, local_port=local_port or DEFAULT_LOCAL_PORT)
        config["presentation"] = dict(DEFAULT_PRESENTATION)
        _check_nesting(config["roots"])
        save_fleet_config(config, component="app", home=home, snapshot=snapshot)
        return config["roots"]
    roots = list(config["roots"])
    for path in paths:
        if str(path) not in roots:
            roots.append(str(path))
    _check_nesting(roots)
    config["roots"] = roots
    if local_port:
        config["local_port"] = int(local_port)
    save_fleet_config(config, component="app", home=home)
    return roots


def remove_library(path, *, home=None) -> list[str]:
    snapshot = _snapshot(home)
    config = snapshot.config("app")
    if config is None:
        raise ValueError("this machine is not enrolled")
    target = str(Path(path).expanduser().resolve())
    if target not in config["roots"]:
        raise ValueError(f"not an enrolled library: {target}")
    if len(config["roots"]) == 1:
        raise ValueError("an enrolled machine keeps at least one library; add another first")
    config["roots"] = [root for root in config["roots"] if root != target]
    save_fleet_config(config, component="app", home=home)
    return config["roots"]


def set_presentation(*, face=None, web=None, home=None) -> dict:
    snapshot = _snapshot(home)
    config = snapshot.config("app")
    if config is None:
        raise ValueError("this machine is not enrolled; add a library first")
    chosen = {**DEFAULT_PRESENTATION, **(config.get("presentation") or {})}
    chosen.update({key: value for key, value in (("face", face), ("web", web)) if value})
    if chosen["face"] == "web" and chosen["web"] == "off":
        raise ValueError("the web face needs the web view on; choose --face window, or a web setting")
    config["presentation"] = chosen
    try:
        save_fleet_config(config, component="app", home=home)
    except SettingsError as exc:
        raise ValueError(str(exc)) from None
    return chosen


def whole_machine_starts() -> list[Path]:
    """Where "look across this machine" starts: every drive on Windows, the home folder elsewhere."""
    if sys.platform == "win32":
        return [Path(f"{letter}:\\") for letter in string.ascii_uppercase if os.path.isdir(f"{letter}:\\")]
    return [Path.home()]


def find_libraries(starts, *, max_depth: int = 4) -> list[dict]:
    """Folders that hold repositories, at most two levels below each start, most first.

    Reads folder names only (no Git, no file contents); hidden and tool folders are skipped."""
    counts: dict[Path, int] = {}
    for start in (Path(path).expanduser().resolve() for path in starts):
        for hit in find_repos(start, max_depth=max_depth):
            if hit.kind == "bare":
                continue
            repo = Path(hit.path)
            relative = repo.relative_to(start).parts if repo != start else ()
            for depth in (1, 2):
                if len(relative) > depth:
                    folder = start.joinpath(*relative[:depth])
                    counts[folder] = counts.get(folder, 0) + 1
    return [{"path": str(path), "repositories": count}
            for path, count in sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))]
