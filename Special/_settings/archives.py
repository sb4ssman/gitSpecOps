"""Archive preference/receipt adapters for a coordinated manager cutover, not a CLI.

load_archive_settings reads an existing common v2 profile, never a legacy registry fallback.
manager_view joins its authoritative archive choices with optional installation/run receipts.
merge_archive_receipts prepares operational state without changing saved archive choices.
save_archive_preferences explicitly writes only those choices through the common CAS writer.

Raw records are trusted local data; use summary() for agent-facing output. Importing, joining
and merging do not inspect repositories, print, log or write. The manager/registry consume
these adapters when a common profile exists; this module enables no migration or action consent.
"""
from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from Special._runtime.files import RuntimeIOError, checked_path
from Special._settings import (SETTINGS_NAME, SettingsError, _unique_object, records,
                               resolve_document, select_home, validate_document)
from Special._settings.store import fingerprint, revision, write_settings

COMPONENT = "archive_manage"
PREFERENCE_FIELDS = {"root", "mode", "approved_remote_prefixes"}
RECEIPT_FIELDS = {
    "installed_at", "updated_at", "git_spec_ops_dir", "python_executable", "runner",
    "launcher", "launcher_type", "repo_count", "last_run_at", "last_run_result",
    "last_run_elapsed_seconds", "last_report", "last_report_at",
}


def _key(root: str) -> str:
    """Lexical, platform-aware matching only; no stat, symlink resolution or repo access."""
    return os.path.normcase(os.path.normpath(root))


def _encoded(document: dict) -> bytes:
    try:
        return json.dumps(document, sort_keys=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise SettingsError("archive settings candidate cannot be encoded") from None


def _archives(value: list[dict]) -> list[dict]:
    """Validate/copy typed choices and reject lexical duplicates without inspecting roots."""
    try:
        records.options(COMPONENT, {"archives": value})
    except records.RecordError as exc:
        raise SettingsError(str(exc)) from None
    keys = [_key(item["root"]) for item in value]
    if len(keys) != len(set(keys)):
        raise SettingsError("archive settings contain duplicate roots")
    return copy.deepcopy(value)


@dataclass(frozen=True)
class ArchiveSettings:
    """Private snapshot of one existing profile; mutable records are checked before saving."""

    home: Path = field(repr=False)
    home_source: str = field(repr=False)
    document: dict = field(repr=False)
    expected_revision: str = field(repr=False)
    document_revision: str = field(repr=False)

    @property
    def archives(self) -> list[dict]:
        """Independent raw preferences; an absent/empty list means no managed archives."""
        selected = self.document.get("components", {}).get(COMPONENT, {})
        return _archives(selected.get("options", {}).get("archives", []))

    def resolved(self):
        """Fresh common resolution, including exclusions; operations must enforce them."""
        return resolve_document(self.document, COMPONENT, home=self.home,
                                home_source=self.home_source)

    def summary(self) -> dict:
        """Counts/preferences only; no roots, remotes, receipts, keys or policy literals."""
        archives = self.archives
        return {"settings": self.resolved().summary(), "archives": len(archives),
                "modes": {mode: sum(item["mode"] == mode for item in archives)
                          for mode in ("update", "sync")}, "runs_operations": False}

    def verify(self) -> None:
        """Refuse changed snapshots/files; never reread a registry or discover settings."""
        _checked_settings_path(self.home)
        if fingerprint(_encoded(self.document)) != self.document_revision:
            raise SettingsError("archive settings snapshot changed; reload before saving")
        if revision(self.home / SETTINGS_NAME) != self.expected_revision:
            raise SettingsError("archive settings changed; reload before saving")


def _checked_settings_path(home: Path) -> Path:
    try:
        return checked_path(home / SETTINGS_NAME)
    except (RuntimeIOError, OSError):
        raise SettingsError("archive settings require readable unlinked storage outside the checkout") from None


def load_archive_settings(home=None) -> ArchiveSettings:
    """Read an existing v2 common profile once; no creation, migration or legacy fallback.

Missing, unreadable, malformed/ambiguous, unsupported or duplicate-root settings raise a
sanitized SettingsError. V1 is not upgraded implicitly. No directory, log or receipt is read
or created beyond checking the selected profile's path ancestry and reading settings.json.
"""
    selected, source = select_home(home, component=COMPONENT)
    path = _checked_settings_path(selected)
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        raise SettingsError("existing common archive settings are required; migration is not automatic") from None
    except OSError:
        raise SettingsError("archive settings could not be read") from None
    try:
        document = validate_document(json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object))
    except (ValueError, UnicodeError, RecursionError):
        raise SettingsError("archive settings are not valid unambiguous configuration") from None
    if document["schema_version"] != 2:
        raise SettingsError("archive preferences require common schema v2; review an explicit upgrade")
    snapshot = ArchiveSettings(selected, source, document, fingerprint(payload), fingerprint(_encoded(document)))
    _ = snapshot.archives  # Validate adapter-level root uniqueness, even for a read-only caller.
    return snapshot


def save_archive_preferences(snapshot: ArchiveSettings, archives: list[dict], *,
                             check_sources: Callable[[], None] | None = None) -> str:
    """Explicitly replace only archive choices, preserving other fields and the schema.

The invoking command must obtain approval; this callable grants no consent and creates no
launchers/receipts. It rechecks snapshot freshness under the common writer's lock. A caller
may add a final read-only receipt/source check; independent legacy writers must still stop
before migration. Semantic no-ops preserve the exact original bytes, after a freshness check.
"""
    snapshot.verify()
    archives = _archives(archives)
    if archives == snapshot.archives:
        if check_sources is not None:
            check_sources()
        snapshot.verify()
        return snapshot.expected_revision
    candidate = copy.deepcopy(snapshot.document)
    candidate.setdefault("components", {}).setdefault(COMPONENT, {}).setdefault("options", {})["archives"] = archives

    def verify_sources():
        snapshot.verify()
        if check_sources is not None:
            check_sources()

    return write_settings(candidate, home=snapshot.home, expected_revision=snapshot.expected_revision,
                          check_sources=verify_sources)


def _receipt_registry(registry: dict | None) -> tuple[dict, dict[str, dict]]:
    """Validate the receipt container/index while retaining unknown historical metadata."""
    if registry is None:
        registry = {"version": 1, "installations": []}
    if (not isinstance(registry, dict) or type(registry.get("version")) is not int
            or registry["version"] not in (1, 2) or not isinstance(registry.get("installations"), list)):
        raise SettingsError("archive receipt registry has an unsupported or invalid format")
    indexed = {}
    for item in registry["installations"]:
        try:
            records.require(isinstance(item, dict))
            records.path(item["root"])
        except (records.RecordError, KeyError):
            raise SettingsError("archive receipt registry contains an invalid root record") from None
        key = _key(item["root"])
        if key in indexed:
            raise SettingsError("archive receipt registry contains duplicate roots")
        indexed[key] = item
    return copy.deepcopy(registry), indexed


def manager_view(snapshot: ArchiveSettings, registry: dict | None = None) -> dict:
    """Join saved choices with receipts, in settings order; no legacy-root enrollment.

Receipts may supply installation/run metadata but cannot replace mode or allowed remotes.
Empty allowed-prefix lists remain empty. Filesystem aliases and operation exclusions need
checking by the invoking operation before inspection/action; this pure conversion performs no I/O.
"""
    _, receipts = _receipt_registry(registry)
    return {"version": 1, "installations": [
        {**copy.deepcopy(receipts.get(_key(item["root"]), {})), **item}
        for item in snapshot.archives]}


def merge_archive_receipts(snapshot: ArchiveSettings, registry: dict | None,
                           updates: list[dict]) -> dict:
    """Prepare receipt-only updates for active roots; never save or rewrite preferences.

Retain inactive/unknown old receipt material for ownership/recovery review. Ignore mode and
prefix copies in manager records, and preserve the original receipt's copies as historical
data. A new receipt contains only its root plus operational fields. Unchanged unknown
metadata may round-trip; new/changed unknown fields, inactive roots, duplicates or invalid
values raise instead of silently discarding data. Returned receipt format v2 requires common
settings; losing that settings file cannot make historical copies authoritative again.
"""
    result, _ = _receipt_registry(registry)
    result["version"] = 2  # Receipt-only state requires common settings, even if that file goes missing.
    active = {_key(item["root"]): item for item in snapshot.archives}
    by_root = {_key(item["root"]): item for item in result["installations"]}
    if not isinstance(updates, list):
        raise SettingsError("archive receipt updates must be a list")
    seen = set()
    for update in updates:
        if not isinstance(update, dict) or not isinstance(update.get("root"), str):
            raise SettingsError("archive receipt update contains invalid fields")
        key = _key(update["root"])
        if key not in active or key in seen:
            raise SettingsError("archive receipt update root is inactive or duplicated")
        seen.add(key)
        original = by_root.get(key, {})
        extra = set(update) - PREFERENCE_FIELDS - RECEIPT_FIELDS
        if any(name not in original or update[name] != original[name] for name in extra):
            raise SettingsError("archive receipt update contains new or changed unknown fields")
        fields = {name: copy.deepcopy(value) for name, value in update.items() if name in RECEIPT_FIELDS}
        for name, value in fields.items():
            if name == "repo_count":
                valid = type(value) is int and value >= 0
            elif name == "last_run_elapsed_seconds":
                valid = (type(value) is int and value >= 0) or (
                    type(value) is float and math.isfinite(value) and value >= 0)
            else:
                valid = (value is None and name in ("last_report", "last_report_at")) or (
                    isinstance(value, str) and "\0" not in value)
            if not valid:
                raise SettingsError("archive receipt update contains an invalid operational value")
        if key not in by_root:
            by_root[key] = {"root": active[key]["root"]}
            result["installations"].append(by_root[key])
        elif "installed_at" in by_root[key]:
            fields.pop("installed_at", None)  # A later install/refresh retains first ownership time.
        by_root[key].update(fields)
    return result
