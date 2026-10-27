"""Read-only local settings resolution. No creation, migration, enrollment or logging.

One settings.json under Basic._paths.config_home(), optionally selected by the caller.
Precedence: defaults, saved common settings, saved component settings, explicit overrides.
Protected values and excluded paths accumulate; an override cannot silently remove them.
Raw values are for trusted operations. Use ResolvedSettings.summary() for agent-facing output.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from Basic._paths import config_home
from Special import _settings_records

SCHEMA_VERSION = 2
SETTINGS_NAME = "settings.json"
COMPONENTS = ("archive_update", "archive_sync", "archive_manage", "duplicate_org", "inventory", "security", "sync", "app")
DEFAULTS = {
    "scope": {"roots": [], "exclude_paths": []},
    "output": {"mode": "stdout", "format": "text", "directory": "reports"},
    "logging": {"enabled": True, "directory": "logs", "level": "INFO",
                "max_bytes": 10 * 1024 * 1024, "backup_count": 3},
    "security": {"never_publish": [], "safe_values": []},
}
_ACCUMULATED = {"scope.exclude_paths", "security.never_publish"}


class SettingsError(ValueError):
    """Invalid/unreadable configuration; messages never include supplied values or paths."""


def _object(value, where):
    if not isinstance(value, dict):
        raise SettingsError(f"{where} must be an object")


def _strings(value, where):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise SettingsError(f"{where} must be a list of nonempty strings")


def _part(value):
    _object(value, "settings")
    if set(value) - DEFAULTS.keys():
        raise SettingsError("settings contain an unknown section")
    for section, entries in value.items():
        _object(entries, section)
        if set(entries) - DEFAULTS[section].keys():
            raise SettingsError(f"{section} contains an unknown field")
        for key, item in entries.items():
            where = f"{section}.{key}"
            if section in ("scope", "security"):
                _strings(item, where)
                if section == "scope" and any("\0" in path for path in item):
                    raise SettingsError(f"{where} contains an invalid path")
            elif key == "directory":
                if not isinstance(item, str) or not item.strip() or "\0" in item:
                    raise SettingsError(f"{where} must be a nonempty path")
            elif where == "output.mode":
                if item not in ("stdout", "file", "both"):
                    raise SettingsError("output.mode must be stdout, file or both")
            elif where == "output.format":
                if item not in ("text", "json"):
                    raise SettingsError("output.format must be text or json")
            elif where == "logging.enabled":
                if type(item) is not bool:
                    raise SettingsError("logging.enabled must be a boolean")
            elif where == "logging.level":
                if item not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                    raise SettingsError("logging.level is unsupported")
            elif type(item) is not int or item < (1 if key == "max_bytes" else 0):
                raise SettingsError(f"{where} must be an integer in its supported range")


def _merge(values, updates, sources, source):
    for section, entries in updates.items():
        for key, value in entries.items():
            dotted = f"{section}.{key}"
            if dotted in _ACCUMULATED:
                values[section][key] = list(dict.fromkeys([*values[section][key], *value]))
                sources[dotted] = list(dict.fromkeys([*sources[dotted], source]))
            else:
                values[section][key] = copy.deepcopy(value)
                sources[dotted] = [source]


def _policy_conflicts(values):
    blocked = {value.casefold() for value in values["security"]["never_publish"]}
    if blocked.intersection(value.casefold() for value in values["security"]["safe_values"]):
        raise SettingsError("security never-publish and safe-value settings conflict")


def validate_document(document):
    """Validate common v1 or typed enrollment v2, without altering the caller's record."""
    _object(document, "settings document")
    version = document.get("schema_version")
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise SettingsError("unsupported settings schema_version")
    allowed = {"schema_version", "defaults", "components"} | ({"machine", "transports"} if version == 2 else set())
    if set(document) - allowed:
        raise SettingsError("settings document contains an unknown field")
    common = document.get("defaults", {})
    components = document.get("components", {})
    _part(common)
    _object(components, "components")
    if set(components) - set(COMPONENTS):
        raise SettingsError("settings name an unsupported component")
    for part in components.values():
        _object(part, "component settings")
        if version == 1 and "options" in part:
            raise SettingsError("component options require settings schema v2")
        _part({key: value for key, value in part.items() if key != "options"})
    if version == 2:
        try:
            _settings_records.document(document)
        except _settings_records.RecordError as exc:
            raise SettingsError(str(exc)) from None
    # Reject a bad saved component even when the current operation selects another one.
    for part in ({}, *components.values()):
        effective = copy.deepcopy(DEFAULTS)
        sources = {f"{section}.{key}": [] for section, entries in DEFAULTS.items() for key in entries}
        _merge(effective, common, sources, "settings")
        _merge(effective, {key: value for key, value in part.items() if key != "options"}, sources, "component")
        _policy_conflicts(effective)
    return copy.deepcopy(document)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("settings contain a duplicate field")
        result[key] = value
    return result


def _absolute(path, base):
    if not isinstance(path, (str, os.PathLike)) or "\0" in str(path):
        raise SettingsError("settings path is invalid")
    path = Path(path).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else base / path))


@dataclass
class ResolvedSettings:
    home: Path = field(repr=False)
    home_source: str
    configured: bool
    component: str | None
    values: dict = field(repr=False)
    sources: dict
    schema_version: int = SCHEMA_VERSION

    def summary(self):
        """Describe policy without returning local paths or protected/safe values."""
        return {"schema_version": self.schema_version, "component": self.component,
                "configured": self.configured, "home_source": self.home_source,
                "scope": {"roots": len(self.values["scope"]["roots"]),
                          "exclude_paths": len(self.values["scope"]["exclude_paths"])},
                "output": {"mode": self.values["output"]["mode"],
                           "format": self.values["output"]["format"]},
                "logging": {key: value for key, value in self.values["logging"].items()
                            if key != "directory"},
                "security": {key: len(value) for key, value in self.values["security"].items()},
                "enrollment": {"machine_configured": bool(self.values.get("machine")),
                               "defined_transports": sorted(self.values.get("transports", {})),
                               "component_option_fields": sorted(self.values.get("options", {}))},
                "sources": copy.deepcopy(self.sources)}


def resolve_settings(component=None, *, home=None, overrides=None):
    """Read and resolve settings, returning fresh values with per-field provenance.

    An absent file is normal first use. An existing invalid/unreadable file is an error.
    Explicit home overrides GITSPECOPS_HOME, which overrides the established OS default.
    Relative explicit home is caller-relative; paths inside settings are home-relative.
    No path is created or checked for runtime usability here; the operation must check it.
    """
    if component is not None and component not in COMPONENTS:
        raise SettingsError("unsupported settings component")
    if home is None:
        if component in (None, "sync", "app") and "GITSPECOPS_SYNC_HOME" in os.environ:
            raise SettingsError("legacy sync home requires migration or an explicit settings home")
        override = os.environ.get("GITSPECOPS_HOME")
        if override is not None and not override.strip():
            raise SettingsError("GITSPECOPS_HOME must not be empty")
        if override is not None and ("\0" in override or not Path(override).expanduser().is_absolute()):
            raise SettingsError("GITSPECOPS_HOME must be an absolute path")
        selected_home = config_home()
        home_source = "environment" if override is not None else "platform-default"
    else:
        if not str(home).strip():
            raise SettingsError("explicit settings home must not be empty")
        selected_home, home_source = home, "explicit"
    selected_home = _absolute(selected_home, Path.cwd())
    path = selected_home / SETTINGS_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if path.is_symlink():
            raise SettingsError("settings file is an unreadable link") from None
        legacy = ("sync-suggester/config.json", "sync-suggester/fleet-app.json",
                  "gitspecops_managed_archives.json", "security/never_publish.txt", "security/safe.txt")
        if any((selected_home / name).exists() for name in legacy):
            raise SettingsError("legacy settings exist; explicit settings migration is required") from None
        document, configured = {"schema_version": SCHEMA_VERSION}, False
    except (OSError, UnicodeError):
        raise SettingsError("settings file could not be read") from None
    else:
        configured = True
        try:
            document = json.loads(text, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            raise SettingsError("settings file is not valid unambiguous JSON") from None
    document = validate_document(document)
    overrides = {} if overrides is None else overrides
    _part(overrides)
    values = copy.deepcopy(DEFAULTS)
    sources = {f"{section}.{key}": ["default"] for section, entries in DEFAULTS.items() for key in entries}
    _merge(values, document.get("defaults", {}), sources, "settings")
    if component is not None:
        selected = document.get("components", {}).get(component, {})
        _merge(values, {key: value for key, value in selected.items() if key != "options"},
               sources, f"component:{component}")
        values["options"] = copy.deepcopy(selected.get("options", {}))
        for key in values["options"]:
            sources[f"options.{key}"] = [f"component:{component}"]
    _merge(values, overrides, sources, "explicit")
    _policy_conflicts(values)
    for key in ("roots", "exclude_paths"):
        values["scope"][key] = list(dict.fromkeys(_absolute(item, selected_home) for item in values["scope"][key]))
    for section in ("output", "logging"):
        values[section]["directory"] = _absolute(values[section]["directory"], selected_home)
    for name in ("machine", "transports"):
        if name in document:
            values[name] = copy.deepcopy(document[name])
            sources[name] = ["settings"]
    return ResolvedSettings(selected_home, home_source, configured, component, values, sources,
                            schema_version=document["schema_version"])
