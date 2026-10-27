"""Read-only legacy-to-common settings preview. Never writes or changes a running component."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from Special._settings import SCHEMA_VERSION, SETTINGS_NAME, SettingsError, _absolute, _unique_object, validate_document
from Special import _settings_records as records
from Special._settings_store import fingerprint, revision

CLI_FIELDS = {"schema_version", "fleet_secret", "machine_id", "machine_label", "state_dir", "state_repo",
              "roots", "stale_hours", "expired_days", "compress_manifests"}
APP_OPTIONS = {"fetch_minutes", "share_names", "baskets", "recovery", "observation_mode", "debounce_seconds",
               "heartbeat", "inventory_notice_acknowledged", "local_port", "git_client"}
APP_FIELDS = {"version", "mode", "machine_id", "label", "fleet_secret", "roots", "transports"} | APP_OPTIONS


def _encoded(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


@dataclass(frozen=True)
class MigrationPreview:
    home: Path = field(repr=False)
    document: dict | None = field(repr=False)
    snapshots: dict = field(repr=False)
    document_revision: str | None = field(repr=False)
    conflicts: tuple[str, ...]
    sources: tuple[str, ...]
    retains_archive_receipts: bool

    @property
    def ready(self):
        return not self.conflicts and self.document is not None

    def summary(self):
        return {"schema_version": SCHEMA_VERSION, "ready": self.ready, "sources": list(self.sources),
                "conflicts": list(self.conflicts), "retains_archive_receipts": self.retains_archive_receipts,
                "components": sorted((self.document or {}).get("components", {})),
                "enables_actions": False, "changes_legacy_files": False}

    def verify(self):
        """Refuse a blocked/tampered preview or changed source/target; no writes."""
        if not self.ready:
            raise SettingsError("migration preview has unresolved conflicts")
        try:
            current = fingerprint(_encoded(self.document))
        except (ValueError, TypeError):
            raise SettingsError("migration preview was changed") from None
        if current != self.document_revision:
            raise SettingsError("migration preview was changed")
        for path, expected in self.snapshots.items():
            if revision(path) != expected:
                raise SettingsError("migration inputs changed; prepare a new preview")


def _same(left, right, key):
    if key in ("path", "executable"):
        return Path(left).expanduser() == Path(right).expanduser()
    return left == right


def _combine(target, incoming, prefix, conflicts):
    for key, value in incoming.items():
        name = f"{prefix}.{key}" if prefix else key
        if key not in target:
            target[key] = copy.deepcopy(value)
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _combine(target[key], value, name, conflicts)
        elif not _same(target[key], value, key):
            conflicts.append(name)


def preview_migration(home, *, sync_directory=None):
    """Read only explicitly located legacy files, producing a private candidate and safe summary.

    Unknown/old records block rather than discard fields. Operational state is retained in
    place. No actual CLI/app reader is switched. Stop legacy writers before any later migration
    write and use preview.verify as the writer's check_sources callback.
    """
    home = _absolute(home, Path.cwd())
    sync = _absolute(sync_directory, Path.cwd()) if sync_directory is not None else home / "sync-suggester"
    paths = {"cli": sync / "config.json", "app": sync / "fleet-app.json",
             "archives": home / "gitspecops_managed_archives.json",
             "never_publish": home / "security" / "never_publish.txt",
             "safe_values": home / "security" / "safe.txt", "target": home / SETTINGS_NAME}
    snapshots, loaded, conflicts = {}, {}, []
    if sync_directory is None and "GITSPECOPS_SYNC_HOME" in os.environ:
        conflicts.append("legacy-sync-location-requires-explicit-choice")
    for label, path in paths.items():
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            if path.is_symlink():
                conflicts.append(f"{label}.unreadable")
            snapshots[path] = None
            continue
        except OSError:
            conflicts.append(f"{label}.unreadable")
            continue
        snapshots[path] = fingerprint(payload)
        if label == "target":
            conflicts.append("target.already-configured")
            continue
        try:
            text = payload.decode("utf-8")
            loaded[label] = (json.loads(text, object_pairs_hook=_unique_object) if label in ("cli", "app", "archives")
                             else [line.strip() for line in text.splitlines()
                                   if line.strip() and not line.lstrip().startswith("#")])
        except (UnicodeError, ValueError, RecursionError):
            conflicts.append(f"{label}.invalid")
    candidate = {"schema_version": SCHEMA_VERSION, "components": {}}
    if not loaded:
        conflicts.append("no-readable-legacy-settings")
    for source in ("cli", "app"):
        if source not in loaded:
            continue
        record = loaded[source]
        try:
            allowed = CLI_FIELDS if source == "cli" else APP_FIELDS
            records.obj(record, allowed)
            records.require(type(record.get("schema_version" if source == "cli" else "version")) is int
                            and record.get("schema_version" if source == "cli" else "version") == (1 if source == "cli" else 5),
                            "unsupported legacy settings version")
            if source == "app":
                records.require(record.get("mode") == "peer")
            machine = {"id": record["machine_id"], "label": record["machine_label" if source == "cli" else "label"],
                       "fleet_secret": record["fleet_secret"]}
            records.machine(machine)
            machine["fleet_secret"] = machine["fleet_secret"].lower()
            _combine(candidate.setdefault("machine", {}), machine, "machine", conflicts)
            if source == "cli":
                records.require(isinstance(record["roots"], list))
                root_map = {}
                for root in record["roots"]:
                    records.obj(root, ("path", "recursive"), ("path",))
                    records.path(root["path"])
                    recursive = root.get("recursive", False)
                    records.boolean(recursive)
                    records.require(root["path"] not in root_map, "duplicate legacy root")
                    root_map[root["path"]] = recursive
                transport = {}
                records.require(not (record.get("state_dir") and record.get("state_repo")))
                if record.get("state_dir") is not None:
                    transport["folder"] = {"path": record["state_dir"]}
                if record.get("state_repo") is not None:
                    transport["repo"] = {"name": record["state_repo"]}
                options = {"root_recursion": root_map, "transport_names": list(transport),
                           "stale_hours": record["stale_hours"], "expired_days": record["expired_days"],
                           "compress_manifests": record.get("compress_manifests", False)}
                roots, component = list(root_map), "sync"
            else:
                roots, component = record["roots"], "app"
                records.strings(roots)
                records.require(bool(roots))
                for root in roots:
                    records.path(root)
                transport = record["transports"]
                records.transports(transport)
                options = {key: copy.deepcopy(record[key]) for key in APP_OPTIONS if key in record}
                records.require({"baskets", "recovery", "observation_mode", "debounce_seconds", "heartbeat",
                                 "inventory_notice_acknowledged", "local_port"} <= set(options))
                options.setdefault("fetch_minutes", 15)
                options.setdefault("share_names", True)
                options["transport_names"] = list(transport)
            records.transports(transport)
            records.options(component, options)
            _combine(candidate.setdefault("transports", {}), transport, "transports", conflicts)
            candidate["components"][component] = {"scope": {"roots": copy.deepcopy(roots)}, "options": options}
        except (records.RecordError, KeyError, TypeError):
            conflicts.append(f"{source}.unsupported-or-invalid")
    if "archives" in loaded:
        try:
            registry = loaded["archives"]
            records.obj(registry, ("version", "installations"), ("version", "installations"))
            records.require(type(registry["version"]) is int and registry["version"] == 1)
            records.require(isinstance(registry["installations"], list))
            archives = []
            for record in registry["installations"]:
                records.require(isinstance(record, dict))
                # All original receipt/last-run fields remain in the untouched registry.
                archives.append({"root": record["root"], "mode": record.get("mode", "update"),
                                 "approved_remote_prefixes": record["approved_remote_prefixes"]})
            records.options("archive_manage", {"archives": archives})
            candidate["components"]["archive_manage"] = {"options": {"archives": archives}}
        except (records.RecordError, KeyError, TypeError):
            conflicts.append("archives.unsupported-or-invalid")
    if "never_publish" in loaded or "safe_values" in loaded:
        candidate["defaults"] = {"security": {name: loaded.get(name, [])
                                               for name in ("never_publish", "safe_values")}}
    try:
        validate_document(candidate)
    except SettingsError:
        conflicts.append("candidate.settings-conflict-or-invalid")
    return MigrationPreview(home, candidate, snapshots, fingerprint(_encoded(candidate)),
                            tuple(dict.fromkeys(conflicts)), tuple(sorted(loaded)), "archives" in loaded)
