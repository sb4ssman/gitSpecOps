"""Explicit validated settings writes: atomic replacement and a cooperating-writer lock."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from Basic._files import atomic_write_bytes
from Special._settings import SETTINGS_NAME, SettingsError, _absolute, validate_document


def fingerprint(payload):
    return hashlib.sha256(payload).hexdigest()


def revision(path):
    """None when absent; otherwise identify the exact bytes without exposing their values."""
    try:
        return fingerprint(Path(path).read_bytes())
    except FileNotFoundError:
        if Path(path).is_symlink():
            raise SettingsError("settings path is an unreadable link") from None
        return None
    except OSError:
        raise SettingsError("settings source could not be read") from None


def _real_path(path):
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) &
                                         getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise SettingsError("settings writes must not traverse links")


def write_settings(document, *, home, expected_revision=None, check_sources=None):
    """Validate and write on explicit invocation; never used implicitly by the resolver.

    None expects an absent destination; replacement requires its exact previous revision.
    check_sources, if supplied, must reject stale migration inputs immediately before replace.
    Independent legacy writers must be stopped for migration: this lock covers cooperating
    settings writers, not unrelated programs or a malicious process changing the directory.
    """
    document = validate_document(document)
    if not isinstance(home, (str, os.PathLike)) or not str(home).strip():
        raise SettingsError("explicit settings home must not be empty")
    if expected_revision is not None and (not isinstance(expected_revision, str) or
                                          re.fullmatch(r"[0-9a-f]{64}", expected_revision) is None):
        raise SettingsError("invalid expected settings revision")
    try:
        payload = (json.dumps(document, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()
    except (ValueError, TypeError):
        raise SettingsError("settings could not be encoded") from None
    destination = _absolute(home, Path.cwd()) / SETTINGS_NAME
    if Path(__file__).resolve().parent.parent in destination.parents:
        raise SettingsError("settings home must be outside the source checkout")
    lock = destination.with_name(".settings.lock")
    owned_lock = False
    committed = False
    try:
        _real_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        owned_lock = True
        os.close(descriptor)
        _real_path(destination)
        if revision(destination) != expected_revision:
            raise SettingsError("settings changed or already exist; review a fresh revision")
        if check_sources is not None:
            check_sources()
        atomic_write_bytes(destination, payload)
        committed = True
    except SettingsError:
        raise
    except FileExistsError:
        raise SettingsError("settings writer is busy; no settings were replaced") from None
    except OSError:
        raise SettingsError("settings write failed; no alternate destination was used") from None
    finally:
        if owned_lock:
            try:
                lock.unlink()
            except OSError:
                if committed:
                    raise SettingsError("settings were saved but lock cleanup failed; explicit review required") from None
                # Preserve the original failure; a remaining lock blocks another writer.
    return fingerprint(payload)
