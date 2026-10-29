"""Pure portable-preference projection and merge; never read/write/sync a user profile.

portable_settings(document) returns an explicitly private value carrier. Its summary/repr
hide policy values. raw_record() is for a selected private conduit, not stdout/logging.
merge_portable(local, record) prepares a candidate while preserving local bindings/additions;
the invoking operation must review policy weakening and save through the revision-checked
writer. This is not automatic enrollment, transport activation or last-writer-wins sync.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from Special._settings import SettingsError, validate_document

PORTABLE_FIELDS = {
    "output": {"mode", "format"},
    "logging": {"enabled", "level", "max_bytes", "backup_count"},
    "security": {"never_publish", "safe_values", "engines"},
}
PORTABLE_OPTIONS = {
    "sync": {"stale_hours", "expired_days", "compress_manifests"},
    "app": {"share_names", "fetch_minutes", "observation_mode", "debounce_seconds", "heartbeat"},
}


def _project_part(part, component=None):
    projected = {}
    for section, allowed in PORTABLE_FIELDS.items():
        entries = {key: copy.deepcopy(value) for key, value in part.get(section, {}).items() if key in allowed}
        if entries:
            projected[section] = entries
    options = {key: copy.deepcopy(value) for key, value in part.get("options", {}).items()
               if key in PORTABLE_OPTIONS.get(component, ())}
    if options:
        projected["options"] = options
    return projected


def _projection(document):
    result = {"schema_version": 2}
    defaults = _project_part(document.get("defaults", {}))
    if defaults:
        result["defaults"] = defaults
    components = {name: _project_part(part, name) for name, part in document.get("components", {}).items()}
    components = {name: part for name, part in components.items() if part}
    if components:
        result["components"] = components
    return result


@dataclass(frozen=True)
class PortableSettings:
    """Sensitive portable master policy/preferences. Safe summary is the presentation seam."""

    document: dict = field(repr=False)

    def raw_record(self):
        """Copy explicit private transfer data; no machine bindings or local policy additions."""
        validated = validate_document(self.document)
        if validated != _projection(validated):
            raise SettingsError("portable settings contain local or unsupported fields")
        return {"schema_version": 1, "settings": copy.deepcopy(validated)}

    def summary(self):
        """Counts/names only; no protected values, local identifiers or raw-value hashes."""
        document = self.raw_record()["settings"]
        parts = [document.get("defaults", {}), *document.get("components", {}).values()]
        return {"schema_version": 1, "components": sorted(document.get("components", {})),
                "preference_fields": sum(len(entries) for part in parts for entries in part.values()),
                "protected_values": sum(len(part.get("security", {}).get("never_publish", ())) for part in parts),
                "contains_machine_bindings": False, "contains_local_policy": False,
                "requires_private_transport": True, "writes_settings": False}


def portable_settings(document) -> PortableSettings:
    """Project an existing common v1/v2 document by allowlist, without mutating it."""
    return PortableSettings(_projection(validate_document(document)))


def merge_portable(local_document, record):
    """Prepare an authoritative portable candidate; preserve local-only fields and validate.

    Missing portable fields mean the shared owner removed those saved overrides. This may
    remove a master block and therefore requires caller review, not an implicit union or
    automatic save. Machine-local blocks survive; master/local safe conflicts are errors.
    Transport revision/conflict ownership is the invoking transport's separate responsibility.
    """
    if not isinstance(record, dict) or set(record) != {"schema_version", "settings"} or \
            type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise SettingsError("unsupported portable settings record")
    incoming = PortableSettings(record["settings"]).raw_record()["settings"]
    candidate = validate_document(local_document)
    candidate["schema_version"] = 2

    def replace_portable(part, shared, component=None):
        result = copy.deepcopy(part)
        for section, allowed in (*PORTABLE_FIELDS.items(), ("options", PORTABLE_OPTIONS.get(component, set()))):
            entries = {key: value for key, value in result.get(section, {}).items() if key not in allowed}
            entries.update(copy.deepcopy(shared.get(section, {})))
            if entries:
                result[section] = entries
            else:
                result.pop(section, None)
        return result

    defaults = replace_portable(candidate.get("defaults", {}), incoming.get("defaults", {}))
    if defaults:
        candidate["defaults"] = defaults
    else:
        candidate.pop("defaults", None)
    components = candidate.setdefault("components", {})
    for name in set(components) | set(incoming.get("components", {})):
        components[name] = replace_portable(components.get(name, {}), incoming.get("components", {}).get(name, {}), name)
    return validate_document(candidate)
