"""Archive choices and receipts at one selected user-data home, never in the checkout.

An existing common settings.json is authoritative; invalid common settings never fall back.
Without it, retain the legacy registry. No automatic migration or enrollment occurs. Common
receipt saves cannot change choices; explicit install/forget changes use the common writer.
Cooperating registry writers lock and reject stale snapshots. Preference/receipt writes are
separate atomic files: partial success is reported, never hidden by rollback or a fallback.
Raw returned records are trusted local data, not a log/agent-summary channel.
"""
from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from Basic._files import atomic_write_bytes
from Special._runtime.files import RuntimeIOError, checked_path, excluded
from Special._settings import SETTINGS_NAME, SettingsError, _unique_object, select_home
from Special._settings.archives import (PREFERENCE_FIELDS, _key, _receipt_registry,
    load_archive_settings, manager_view, merge_archive_receipts, save_archive_preferences)
from Special._settings.store import fingerprint, revision

REGISTRY_NAME = "gitspecops_managed_archives.json"


def registry_path(home=None) -> Path:
    return select_home(home, component="archive_manage")[0] / REGISTRY_NAME


def _checked(path: Path) -> Path:
    try:
        return checked_path(path)
    except (RuntimeIOError, OSError):
        raise SettingsError("archive storage must be accessible, unlinked and outside the checkout") from None


class RegistryData(dict):
    """Mutable manager view plus private source revisions for explicit subsequent saves."""

    def __init__(self, data, path, raw, raw_revision, preferences):
        super().__init__(data)
        self.path, self.raw, self.raw_revision = path, raw, raw_revision
        self.preferences = preferences

    @property
    def home(self):
        return self.path.parent

    def verify(self):
        """Refuse changed receipts/preferences or a newly appearing authority before effects."""
        _checked(self.path)
        _checked(self.home / SETTINGS_NAME)
        if revision(self.path) != self.raw_revision:
            raise SettingsError("archive receipts changed; reload before continuing")
        if self.preferences is not None:
            self.preferences.verify()
        elif revision(self.home / SETTINGS_NAME) is not None:
            raise SettingsError("archive settings authority changed; reload before continuing")


def _preferences(home):
    path = _checked(home / SETTINGS_NAME)
    return load_archive_settings(home) if revision(path) is not None else None


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


def load_registry(path: Path | None = None, *, home=None) -> RegistryData:
    """Read the selected authority and receipts; missing legacy state is empty, corruption errors."""
    if path is not None and home is not None:
        raise SettingsError("select an archive registry path or a settings home, not both")
    path = _checked(Path(path) if path is not None else registry_path(home))
    preferences = _preferences(path.parent)
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        raw, raw_revision = {"version": 1, "installations": []}, None
    except OSError:
        raise SettingsError("archive receipts could not be read") from None
    else:
        try:
            raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError, RecursionError):
            raise SettingsError("archive receipts are not valid unambiguous JSON") from None
        raw_revision = fingerprint(payload)
    raw, _ = _receipt_registry(raw)
    if raw["version"] == 2 and preferences is None:
        raise SettingsError("common archive settings are missing; receipt-only state cannot supply preferences")
    data = manager_view(preferences, raw) if preferences is not None else copy.deepcopy(raw)
    result = RegistryData(data, path, raw, raw_revision, preferences)
    result.verify()
    return result


@contextmanager
def _writer(data: RegistryData):
    """Serialize cooperating registry writers; never reclaim somebody else's lock."""
    _checked(data.path)
    lock = data.path.with_name(".archive-registry.lock")
    owned = False
    state = {"saved": False}
    try:
        data.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        owned = True
        os.close(fd)
        data.verify()
        yield state
    except FileExistsError:
        raise SettingsError("archive registry writer is busy; reload before retrying") from None
    except OSError:
        raise SettingsError("archive state write failed; no alternate destination was used") from None
    finally:
        if owned:
            try:
                lock.unlink()
            except OSError:
                if state["saved"]:
                    raise SettingsError("archive state was saved but lock cleanup failed; explicit review required") from None


def _write_raw(data, raw, state):
    """Atomically save checked receipts, then advance only this invocation's source revision."""
    data.verify()
    try:
        payload = (json.dumps(raw, indent=2, allow_nan=False) + "\n").encode("utf-8")
        atomic_write_bytes(data.path, payload)
    except (OSError, ValueError, TypeError):
        raise SettingsError("archive receipt write failed; no alternate destination was used") from None
    state["saved"] = True
    data.raw, data.raw_revision = copy.deepcopy(raw), fingerprint(payload)


def _require_common_settings(data, state):
    """Mark retained copies as receipts before changing common choices; never mark on read."""
    if data.raw["version"] != 2:
        raw = copy.deepcopy(data.raw)
        raw["version"] = 2
        _write_raw(data, raw, state)


def save_registry(data: dict, path: Path | None = None, *, home=None) -> Path:
    """Save run/receipt state only under common settings; refuse stale views, preserve choices."""
    if isinstance(data, RegistryData):
        source = data
        selected = _checked(Path(path)) if path is not None else registry_path(home) if home is not None else data.path
        if selected != data.path or (path is not None and home is not None):
            raise SettingsError("archive snapshot belongs to a different storage selection")
    else:
        source = load_registry(path, home=home)
        if source.preferences is not None:
            raise SettingsError("common receipt writes require the original revision-checked registry snapshot")
    with _writer(source) as state:
        raw = (merge_archive_receipts(source.preferences, source.raw, data["installations"])
               if source.preferences is not None else _receipt_registry(data)[0])
        _write_raw(source, raw, state)
    return source.path


def upsert_record(record: InstallRecord, path: Path | None = None, *, home=None,
                  expected: RegistryData | None = None) -> None:
    """Explicit install preferences plus receipt; preserve first install time and report partial save."""
    if expected is not None and (path is not None or home is not None):
        raise SettingsError("select an archive snapshot or a storage location, not both")
    data = expected if expected is not None else load_registry(path, home=home)
    payload = asdict(record)
    with _writer(data) as state:
        if data.preferences is None:
            raw = copy.deepcopy(data.raw)
            for item in raw["installations"]:
                if _key(item["root"]) == _key(record.root):
                    payload["installed_at"] = item.get("installed_at", record.installed_at)
                    item.update(payload)
                    break
            else:
                raw["installations"].append(payload)
            _write_raw(data, raw, state)
            return
        archives = data.preferences.archives
        choice = {key: payload[key] for key in PREFERENCE_FIELDS}
        for index, item in enumerate(archives):
            if _key(item["root"]) == _key(record.root):
                archives[index] = choice
                break
        else:
            archives.append(choice)
        candidate = copy.deepcopy(data.preferences.document)
        candidate.setdefault("components", {}).setdefault("archive_manage", {}).setdefault("options", {})["archives"] = archives
        future = replace(data.preferences, document=candidate)
        raw = merge_archive_receipts(future, data.raw, [payload])  # Validate before either save.
        _require_common_settings(data, state)
        try:
            new_revision = save_archive_preferences(data.preferences, archives, check_sources=data.verify)
        except SettingsError as exc:
            raise SettingsError(f"receipt-only state was retained; preference saving did not finish: {exc}") from None
        state["saved"] = True
        try:
            data.preferences = load_archive_settings(data.home)
            if data.preferences.expected_revision != new_revision:
                raise SettingsError("archive settings changed after preference saving")
            _write_raw(data, raw, state)
        except SettingsError:
            raise SettingsError("archive preferences were saved but receipt saving failed; review partial installation") from None


def forget_installation(root: Path, path: Path | None = None, *, home=None) -> bool:
    """Remove active registration; common-profile receipts/launchers remain for ownership review."""
    data = load_registry(path, home=home)
    key = _key(str(Path(os.path.abspath(root.expanduser()))))
    kept = [item for item in data["installations"] if _key(item["root"]) != key]
    if len(kept) == len(data["installations"]):
        data.verify()
        return False
    with _writer(data) as state:
        if data.preferences is not None:
            _require_common_settings(data, state)
            save_archive_preferences(data.preferences,
                [{name: item[name] for name in PREFERENCE_FIELDS} for item in kept], check_sources=data.verify)
            state["saved"] = True
        else:
            raw = copy.deepcopy(data.raw)
            raw["installations"] = kept
            _write_raw(data, raw, state)
    return True


def registered_roots(path: Path | None = None, *, home=None) -> list[str]:
    """Common choices are strict and authoritative; only the legacy optional hint is tolerant."""
    if path is not None and home is not None:
        raise SettingsError("select an archive registry path or a settings home, not both")
    path = _checked(Path(path) if path is not None else registry_path(home))
    preferences = _preferences(path.parent)
    if preferences is not None:
        exclusions = preferences.resolved().values["scope"]["exclude_paths"]
        roots = [item["root"] for item in preferences.archives]
        for root in roots:
            _checked(Path(root))
            if excluded(Path(root), exclusions, contains=True):
                raise SettingsError("managed archive conflicts with effective scope exclusions")
        return roots
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    installations = data.get("installations") if isinstance(data, dict) else None
    if isinstance(data, dict) and data.get("version") == 2:
        raise SettingsError("common archive settings are missing; receipt-only state cannot supply root hints")
    if not isinstance(installations, list):
        return []
    return [item["root"] for item in installations
            if isinstance(item, dict) and isinstance(item.get("root"), str) and item["root"]]
