"""What this machine observes, read for one local operation: roots, baskets, identity.

Why:          Special operations (catch up, audit, materialize, live buffers, safe-to-wipe's
              local half) act on the repositories this machine observes. They must work with
              no fleet running and without the fleet's full configuration rules.
Reads:        the settings profile's app enrollment, or only the roots given on the
              command line.
May change:   nothing.
Results:      a plain dict for Special._sync.inventory.IncrementalObserver.
Layer:        Special: this machine, once.
Status:       working
"""
from __future__ import annotations

from pathlib import Path

from Special._settings.fleet import load_fleet_settings
from Special._sync import baskets
from Special._sync.manifest import is_fleet_secret, new_fleet_secret

LOCAL_ID = "this-machine"


def _local(roots) -> dict:
    """A one-run selection: every repository under the given roots, a throwaway identity.

    The secret only salts repository ids inside this process; nothing here is published."""
    return {"roots": [str(Path(root).expanduser().resolve()) for root in roots],
            "baskets": baskets.DEFAULT_SCOPES, "fleet_secret": new_fleet_secret(),
            "machine_id": LOCAL_ID, "label": LOCAL_ID, "share_names": True}


def load_selection(config_dir=None, *, home=None, roots=None) -> dict:
    """Roots from the command line win; otherwise the saved enrollment, read-only."""
    if roots:
        missing = [str(root) for root in roots if not Path(root).expanduser().is_dir()]
        if missing:
            raise ValueError(f"not an existing folder: {', '.join(missing)}")
        return _local(roots)
    snapshot = load_fleet_settings(home)
    config = snapshot.config("app") if snapshot is not None else None
    if config is None:
        raise ValueError("no saved repository roots; pass --root, or enroll with "
                         "gitso enroll-machine add <library folder>")
    if not config.get("roots") or any(not Path(root).is_dir() for root in config["roots"]):
        raise ValueError("every configured repository root must exist")
    if not is_fleet_secret(config.get("fleet_secret")):
        raise ValueError("the saved configuration has no valid fleet identity")
    selection = dict(config)
    selection["baskets"] = baskets.validate_scopes(config.get("baskets") or baskets.DEFAULT_SCOPES)
    selection.setdefault("label", config.get("machine_id") or LOCAL_ID)
    return selection
