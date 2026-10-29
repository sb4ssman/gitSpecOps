"""Reviewed setup plans for the standalone updater; no I/O on import or implicit saves.

prepare_setup reads an explicitly selected profile and returns a private candidate plus a safe
summary. save_setup requires its exact review id and rechecks all snapshots under the writer's
lock. Legacy activation remains unavailable until its active readers/writers are coordinated.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from Special._runtime.files import RuntimeIOError, checked_path, excluded
from Special._runtime.output import conceal
from Special._settings import (SCHEMA_VERSION, SETTINGS_NAME, SettingsError,
                               _unique_object, legacy_locations, resolve_document,
                               select_home, validate_document)
from Special._settings.migration import preview_migration
from Special._settings.store import fingerprint, revision, write_settings

COMPONENT = "archive_update"


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")


def _review_id(home, document, snapshots):
    return fingerprint(_encoded({"home": str(home), "candidate": document,
        "sources": {str(path): value for path, value in snapshots.items()}}))[:32]


@dataclass(frozen=True)
class SetupPlan:
    home: Path = field(repr=False)
    home_source: str
    document: dict = field(repr=False)
    snapshots: dict = field(repr=False)
    expected_revision: str | None = field(repr=False)
    review_id: str
    changes: tuple[str, ...]
    blockers: tuple[str, ...]
    migration: dict | None = field(repr=False)

    @property
    def ready(self):
        return not self.blockers

    def summary(self):
        """No paths, policy values, identities, keys or original-byte revisions."""
        resolved = resolve_document(self.document, COMPONENT, home=self.home,
                                    home_source=self.home_source,
                                    configured=self.expected_revision is not None)
        return {"component": COMPONENT, "ready": self.ready, "review_id": self.review_id,
                "target": "existing" if self.expected_revision is not None else "new",
                "changes": list(self.changes), "blockers": list(self.blockers),
                "candidate": resolved.summary(), "migration": copy.deepcopy(self.migration),
                "runs_operations": False, "changes_legacy_files": False}

    def paths(self):
        """Explicit local-review channel: paths only, never policy/identity/transport values."""
        resolved = resolve_document(self.document, COMPONENT, home=self.home)
        paths = {"settings": str(self.home / SETTINGS_NAME),
                "roots": [str(path) for path in resolved.values["scope"]["roots"]],
                "exclude_paths": [str(path) for path in resolved.values["scope"]["exclude_paths"]],
                "report_directory": str(resolved.values["output"]["directory"]),
                "log_directory": str(resolved.values["logging"]["directory"])}
        secret = self.document.get("machine", {}).get("fleet_secret")
        return conceal(paths, (secret,) if secret else ())

    def verify(self):
        """Refuse changed candidates, targets or legacy source files; never writes."""
        if not self.ready:
            raise SettingsError("legacy readers must be coordinated before activating this migration")
        try:
            current_id = _review_id(self.home, self.document, self.snapshots)
        except (ValueError, TypeError):
            raise SettingsError("setup candidate changed; review a new preview") from None
        if current_id != self.review_id:
            raise SettingsError("setup candidate changed; review a new preview")
        for path, expected in self.snapshots.items():
            if revision(path) != expected:
                raise SettingsError("settings or legacy inputs changed; review a new preview")


def migration_status(home=None, *, sync_directory=None, show_paths=False):
    """Safe migration preview, distinguishing valid mapping from safe activation."""
    selected, _ = select_home(home, component=COMPONENT)
    preview = preview_migration(selected, sync_directory=sync_directory)
    summary = preview.summary()
    summary["mapping_ready"] = summary.pop("ready")
    summary.update(activation_ready=False,
                   activation_blockers=["general legacy activation is not implemented; archive/policy-only profiles can use settings-existing-plan"])
    if show_paths:
        secret = (preview.document or {}).get("machine", {}).get("fleet_secret")
        summary["paths"] = conceal({label: str(path) for label, path in
                                   legacy_locations(selected, sync_directory=sync_directory).items()},
                                  (secret,) if secret else ())
    return summary


def prepare_setup(home=None, patch=None, *, clear_exclusions=False, sync_directory=None) -> SetupPlan:
    """Create/edit only archive_update fields; preserve all other settings and legacy data.

Root/output/log fields replace their component values. Exclusions add unless the caller
explicitly selects clear_exclusions; inherited common exclusions remain effective regardless.
Fresh-profile saving refuses existing legacy sources. Existing common profiles may edit only
this already-adopted component; this is not approval to change legacy-owned configuration.
"""
    selected, home_source = select_home(home, component=COMPONENT)
    target = selected / SETTINGS_NAME
    try:
        checked_path(target)
    except RuntimeIOError:
        raise SettingsError("use an unlinked settings home outside this source checkout") from None
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        if target.is_symlink():
            raise SettingsError("settings file is an unreadable link") from None
        original, expected = {"schema_version": SCHEMA_VERSION}, None
    except OSError:
        raise SettingsError("settings file could not be read") from None
    else:
        expected = fingerprint(raw)
        try:
            original = validate_document(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
        except (ValueError, UnicodeError, RecursionError):
            raise SettingsError("settings file is not valid unambiguous configuration") from None
    locations = legacy_locations(selected, sync_directory=sync_directory)
    snapshots = {target: expected, **{path: revision(path) for path in locations.values()}}
    legacy = [label for label, path in locations.items() if snapshots[path] is not None]
    blockers, migration = [], None
    if expected is None and legacy:
        blockers.append("legacy_readers_not_cut_over")
        migration = migration_status(selected, sync_directory=sync_directory)
    patch = {} if patch is None else copy.deepcopy(patch)
    if not isinstance(patch, dict) or set(patch) - {"scope", "output", "logging"}:
        raise SettingsError("this setup item edits only updater scope, output and logging")
    # The common validator checks partial sections without interpreting them as defaults.
    resolve_document({"schema_version": SCHEMA_VERSION}, COMPONENT, home=selected, overrides=patch)
    candidate = copy.deepcopy(original)
    current = candidate.setdefault("components", {}).setdefault(COMPONENT, {})
    before = copy.deepcopy(current)
    for section, values in patch.items():
        current.setdefault(section, {}).update(values)
    if "exclude_paths" in patch.get("scope", {}) and not clear_exclusions:
        current["scope"]["exclude_paths"] = list(dict.fromkeys(
            [*before.get("scope", {}).get("exclude_paths", []), *patch["scope"]["exclude_paths"]]))
    elif clear_exclusions:
        current.setdefault("scope", {})["exclude_paths"] = patch.get("scope", {}).get("exclude_paths", [])
    candidate = validate_document(candidate)
    resolved = resolve_document(candidate, COMPONENT, home=selected)
    exclusions = resolved.values["scope"]["exclude_paths"]
    if any(excluded(root, exclusions) for root in resolved.values["scope"]["roots"]):
        raise SettingsError("updater roots conflict with the effective scope exclusions")
    try:
        # Validate storage choices without creating them or executing an operation.
        checked_path(target)
        for section, active in (("output", resolved.values["output"]["mode"] != "stdout"),
                                ("logging", resolved.values["logging"]["enabled"])):
            if active:
                path = resolved.values[section]["directory"]
                checked_path(path)
                if path.exists() and not path.is_dir():
                    raise SettingsError("selected runtime storage is not a directory")
                if excluded(path, exclusions, contains=True):
                    raise SettingsError("runtime storage conflicts with the effective exclusions")
    except RuntimeIOError:
        raise SettingsError("use unlinked settings/runtime storage outside this source checkout") from None
    changes = []
    if expected is None:
        changes.append("create_settings")
    for section, values in current.items():
        if isinstance(values, dict):
            changes.extend(f"components.{COMPONENT}.{section}.{key}" for key, value in values.items()
                           if value != before.get(section, {}).get(key))
    return SetupPlan(selected, home_source, candidate, snapshots, expected,
                     _review_id(selected, candidate, snapshots), tuple(changes), tuple(blockers), migration)


def save_setup(plan: SetupPlan, approval: str) -> str | None:
    """Save only a fresh approved plan using the existing atomic/revision-checked writer."""
    if approval != plan.review_id:
        raise SettingsError("a matching preview review id is required before saving")
    plan.verify()
    if not plan.changes:
        return plan.expected_revision
    return write_settings(plan.document, home=plan.home, expected_revision=plan.expected_revision,
                          check_sources=plan.verify)
