"""Common fleet settings adapters; no enrollment, network, inventory or implicit writes.

load_fleet_settings returns an existing common snapshot, or None for a legacy-only home.
Its config(component) projects the saved sync/app selection into the existing runtime shape.
save_fleet_config requires that snapshot (or its bound mutable view), preserves other owners,
and rejects shared identity/transport changes affecting another enrolled component.

Fleet state/catalogs remain in a separately selected directory. --config-dir never selects
a common profile: --settings-home / GITSPECOPS_HOME do. Legacy files are never imported here.
Raw dict contents are trusted local data; repr/summary omit secrets, paths and identities.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from Special._runtime.files import checked_path, excluded, linked
from Special._settings import SETTINGS_NAME, SettingsError, _absolute, resolve_document, select_home, validate_document
from Special._settings.store import fingerprint, read_settings_document, write_settings

SYNC_OPTIONS = {"root_recursion", "transport_names", "stale_hours", "expired_days", "compress_manifests"}
APP_REQUIRED = {"transport_names", "baskets", "recovery", "observation_mode", "debounce_seconds",
                "heartbeat", "inventory_notice_acknowledged", "local_port"}
APP_OPTIONS = APP_REQUIRED | {"fetch_minutes", "share_names", "git_client"}


def fleet_home(home=None):
    """Choose common settings independently of the legacy fleet-state override."""
    return select_home(home, component="sync", allow_legacy_sync_home=True)[0]


def fleet_directory(directory=None, *, home=None):
    """Select runtime/legacy state without creating it; explicit directory wins."""
    if directory is None:
        directory = os.environ.get("GITSPECOPS_SYNC_HOME")
        if directory is None:
            directory = fleet_home(home) / "sync-suggester"
        elif not directory.strip() or not Path(directory).expanduser().is_absolute():
            raise SettingsError("legacy sync directory must be an absolute nonempty path")
    if not str(directory).strip():
        raise SettingsError("fleet state directory must not be empty")
    return checked_path(Path(directory))


def _digest(document):
    try:
        return fingerprint(json.dumps(document, sort_keys=True, allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):
        raise SettingsError("fleet settings snapshot cannot be encoded") from None


class FleetConfig(dict):
    """Mutable runtime view with private source revision; serialization stays a plain record."""

    def __init__(self, value, snapshot, component):
        super().__init__(copy.deepcopy(value))
        self.snapshot, self.component = snapshot, component
        self.original = copy.deepcopy(value)

    def __repr__(self):
        return f"FleetConfig(component={self.component!r}, values=hidden)"


@dataclass(frozen=True)
class FleetSettings:
    home: Path = field(repr=False)
    document: dict = field(repr=False)
    revision: str = field(repr=False)
    digest: str = field(repr=False)

    def verify(self):
        """Reject file changes and mutation of the trusted in-memory snapshot."""
        if _digest(self.document) != self.digest:
            raise SettingsError("fleet settings snapshot changed; reload before saving")
        if read_settings_document(self.home)[1] != self.revision:
            raise SettingsError("fleet settings changed; reload before saving")

    def summary(self):
        return {"common_settings": True, "enrolled_components": [name for name in ("sync", "app")
                if self.document.get("components", {}).get(name, {}).get("options")],
                "changes_legacy_files": False}

    def check_identity(self, machine_id=None, label=None, secret=None):
        """Per-component setup cannot replace an existing shared machine identity."""
        prior = self.document.get("machine")
        if prior is not None and ((machine_id is not None and machine_id != prior["id"]) or
                                  (label is not None and label != prior["label"]) or
                                  (secret is not None and secret.lower() != prior["fleet_secret"].lower())):
            raise SettingsError("shared machine identity differs; coordinate identity changes explicitly")

    def transport_changes(self, component, definitions):
        """Validate proposed definitions before optional network/setup effects; no writes."""
        shared = self.document.get("transports", {})
        other = "app" if component == "sync" else "sync"
        selected = self.document.get("components", {}).get(other, {}).get("options", {}).get("transport_names", [])
        changes = {}
        for name, definition in definitions.items():
            old = shared.get(name, {})
            proposed = {**old, **copy.deepcopy(definition)} if component == "sync" else copy.deepcopy(definition)
            comparable = copy.deepcopy(old)
            if component == "app" and name in ("folder", "repo") and old:
                comparable.setdefault("seconds", 300 if name == "folder" else 1800)
            if proposed != comparable and name in selected:
                raise SettingsError("transport is selected by another component; coordinate its change explicitly")
            if proposed != comparable:
                changes[name] = proposed
        return changes

    def check_roots(self, component, roots):
        """Refuse linked or excluded intersections before inspection, including run overrides.

        Partial-root exclusion needs discovery support; until then refuse the whole scope.
        Source checkouts are valid inspection targets, unlike runtime destinations.
        """
        settings = resolve_document(self.document, component, home=self.home)
        for root in roots:
            path = Path(os.path.abspath(Path(root).expanduser()))
            if any(linked(part) for part in (path, *path.parents)):
                raise SettingsError("fleet scope traverses a link; no inventory was started")
            if excluded(path, settings.values["scope"]["exclude_paths"], contains=True):
                raise SettingsError("fleet scope intersects an exclusion; no inventory was started")

    def config(self, component):
        """Project only an explicitly enrolled component; never inherit a peer's selection."""
        if component not in ("sync", "app"):
            raise SettingsError("unsupported fleet settings component")
        options = self.document.get("components", {}).get(component, {}).get("options", {})
        if not options:
            return None
        required = SYNC_OPTIONS if component == "sync" else APP_REQUIRED
        if not required <= set(options) or "machine" not in self.document:
            raise SettingsError("fleet enrollment is incomplete; review common settings")
        resolved = resolve_document(self.document, component, home=self.home)
        roots = [str(root) for root in resolved.values["scope"]["roots"]]
        self.check_roots(component, roots)
        machine = self.document["machine"]
        common = {"machine_id": machine["id"], "fleet_secret": machine["fleet_secret"]}
        transports = self.document.get("transports", {})
        names = options["transport_names"]
        if component == "sync":
            raw_recursion = options["root_recursion"]
            recursion = {str(_absolute(root, self.home)): recursive for root, recursive in raw_recursion.items()}
            if len(recursion) != len(raw_recursion) or set(recursion) != set(roots):
                raise SettingsError("fleet root recursion does not match the selected roots")
            value = {**common, "schema_version": 1, "machine_label": machine["label"],
                     "roots": [{"path": root, "recursive": recursion[root]} for root in roots],
                     "state_dir": transports["folder"]["path"] if "folder" in names else None,
                     "state_repo": transports["repo"]["name"] if "repo" in names else None,
                     **{key: copy.deepcopy(options[key]) for key in
                        ("stale_hours", "expired_days", "compress_manifests")}}
        else:
            selected = {key: copy.deepcopy(transports[key]) for key in names}
            for name, seconds in (("folder", 300), ("repo", 1800)):
                if name in selected:
                    selected[name].setdefault("seconds", seconds)
            value = {**common, "version": 5, "mode": "peer", "label": machine["label"],
                     "roots": roots, "transports": selected,
                     **{key: copy.deepcopy(item) for key, item in options.items() if key != "transport_names"}}
            value.setdefault("fetch_minutes", 15)
            value.setdefault("share_names", True)
        return FleetConfig(value, self, component)


def load_fleet_settings(home=None):
    """Guard an existing common document; an absent one alone permits legacy readers."""
    selected = fleet_home(home)
    path = checked_path(selected / SETTINGS_NAME)
    if not path.exists() and not path.is_symlink():
        return None
    document, revision = read_settings_document(selected)
    return FleetSettings(selected, document, revision, _digest(document))


def save_fleet_config(config, *, component, home=None, snapshot=None):
    """Save an approved component choice to an existing common profile, never a legacy copy.

    Shared identity cannot be replaced by per-component setup. A selected transport used by
    another enrolled component cannot be changed here. Removing a selection retains its shared
    definition. All other settings survive. No settings activation or transaction is implied.
    """
    allowed = ({"schema_version", "machine_id", "machine_label", "fleet_secret", "roots", "state_dir", "state_repo",
                "stale_hours", "expired_days", "compress_manifests"} if component == "sync" else
               {"version", "mode", "machine_id", "label", "fleet_secret", "roots", "transports"} | APP_OPTIONS - {"transport_names"})
    if not isinstance(config, dict) or set(config) - allowed:
        raise SettingsError("unsupported fleet runtime fields; no settings were saved")
    if isinstance(config, FleetConfig):
        if config.component != component:
            raise SettingsError("fleet component does not match the loaded snapshot")
        if snapshot is not None and snapshot is not config.snapshot:
            raise SettingsError("fleet snapshot does not match the loaded configuration")
        snapshot = config.snapshot
    if snapshot is None or snapshot.home != fleet_home(home):
        raise SettingsError("common fleet saves require the selected source snapshot")
    snapshot.verify()
    baseline = snapshot.config(component)
    if baseline is not None and dict(config) == dict(baseline):
        return snapshot.home / SETTINGS_NAME
    candidate = copy.deepcopy(snapshot.document)
    if candidate["schema_version"] != 2:
        raise SettingsError("fleet enrollment requires common settings v2; no upgrade was performed")
    machine = {"id": config["machine_id"], "label": config["machine_label" if component == "sync" else "label"],
               "fleet_secret": config["fleet_secret"]}
    snapshot.check_identity(machine["id"], machine["label"], machine["fleet_secret"])
    candidate.setdefault("machine", machine)
    if component == "sync":
        roots = [item["path"] for item in config["roots"]]
        definitions = {}
        if config.get("state_dir") is not None:
            definitions["folder"] = {"path": config["state_dir"]}
        if config.get("state_repo") is not None:
            definitions["repo"] = {"name": config["state_repo"]}
        options = {key: copy.deepcopy(config[key]) for key in ("stale_hours", "expired_days")}
        options["compress_manifests"] = config.get("compress_manifests", False)
        options["root_recursion"] = {item["path"]: item.get("recursive", False) for item in config["roots"]}
    elif component == "app":
        roots = config["roots"]
        definitions = config["transports"]
        options = {key: copy.deepcopy(config[key]) for key in APP_OPTIONS - {"transport_names"} if key in config}
    else:
        raise SettingsError("unsupported fleet settings component")
    snapshot.check_roots(component, roots)
    options["transport_names"] = list(definitions)
    shared = candidate.setdefault("transports", {})
    other = "app" if component == "sync" else "sync"
    shared.update(snapshot.transport_changes(component, definitions))
    owner = candidate.setdefault("components", {}).setdefault(component, {})
    prior_roots = None
    if baseline is not None:
        prior_roots = [item["path"] for item in baseline["roots"]] if component == "sync" else baseline["roots"]
    if roots != prior_roots:
        owner.setdefault("scope", {})["roots"] = copy.deepcopy(roots)
    prior_options = owner.setdefault("options", {})
    for key, value in options.items():
        # Preserve omitted optional defaults and unrelated component options when unchanged.
        if key in prior_options or baseline is None or key == "transport_names" or value != baseline.get(key):
            prior_options[key] = value
    candidate = validate_document(candidate)
    # Validate both projections so shared changes cannot produce incomplete runtime records.
    trial = FleetSettings(snapshot.home, candidate, snapshot.revision, _digest(candidate))
    trial.config(component)
    trial.config(other)
    saved_revision = write_settings(candidate, home=snapshot.home, expected_revision=snapshot.revision,
                                    check_sources=snapshot.verify)
    if isinstance(config, FleetConfig):
        config.snapshot = FleetSettings(snapshot.home, candidate, saved_revision, _digest(candidate))
        config.original = copy.deepcopy(dict(config))
    return snapshot.home / SETTINGS_NAME
