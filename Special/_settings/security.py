"""Explicit common-policy editing over the shared settings writer; not a policy CLI.

load_security_settings requires an existing common profile. save_security_settings replaces
only the supplied defaults.security fields after the invoking interface obtains approval.
Omitted fields and component policies remain intact; inherited blocks cannot be cleared by
changing another owner. No identity discovery, legacy-file edits, enrollment or migration.

Raw records are for trusted code. summary()/repr hide policy values and local identifiers.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from Special._settings import DEFAULTS, SettingsError, resolve_document, select_home, validate_document
from Special._settings.store import fingerprint, read_settings_document, write_settings


def _digest(document):
    try:
        return fingerprint(json.dumps(document, sort_keys=True, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError):
        raise SettingsError("security settings candidate cannot be encoded") from None


@dataclass(frozen=True)
class SecuritySettings:
    """One private editable snapshot, bound to the selected profile's original bytes."""

    home: Path = field(repr=False)
    home_source: str = field(repr=False)
    document: dict = field(repr=False)
    expected_revision: str = field(repr=False)
    document_revision: str = field(repr=False)

    def resolved(self, component="security"):
        """Resolve a fresh component policy without reading any files or discovering identity."""
        return resolve_document(self.document, component, home=self.home, home_source=self.home_source)

    def owned_policy(self) -> dict:
        """Raw common-owned lists only, distinct from effective accumulated component values."""
        owned = self.document.get("defaults", {}).get("security", {})
        return {name: copy.deepcopy(owned.get(name, [])) for name in DEFAULTS["security"]}

    def summary(self) -> dict:
        """Counts and source labels only; no policies, identities, profile paths or revisions."""
        owned = self.owned_policy()
        return {"component": "security", "owned_values": {name: len(owned[name]) for name in ("never_publish", "safe_values")},
                "local_values": {name: len(owned[name]) for name in ("local_never_publish", "local_safe_values")},
                "engines": list(owned["engines"]),
                "effective": self.resolved().summary(), "runs_operations": False, "changes_legacy_files": False}

    def verify(self) -> None:
        """Refuse stale files or mutated snapshots before an explicit save."""
        if _digest(self.document) != self.document_revision:
            raise SettingsError("security settings snapshot changed; reload before saving")
        # Use the same guarded reader as initial loading, including link/source checks.
        _, current = read_settings_document(self.home)
        if current != self.expected_revision:
            raise SettingsError("security settings changed; reload before saving")


def load_security_settings(home=None) -> SecuritySettings:
    """Load an existing common v1/v2 profile for an editor; never create or import policy."""
    selected, source = select_home(home, component="security")
    document, expected = read_settings_document(selected)
    return SecuritySettings(selected, source, document, expected, _digest(document))


def save_security_settings(snapshot: SecuritySettings, updates: dict, *,
                           check_sources: Callable[[], None] | None = None) -> str:
    """Explicitly replace selected common-owned policy lists; preserve every other field.

    The calling interface must obtain approval, including any removal/allowance expansion.
    Exact case-insensitive block/safe conflicts anywhere in the saved profile are errors.
    Source checks run under the shared writer lock for real writes. A semantic no-op retains
    exact original bytes after freshness checking. No text policy or other state is written.
    """
    snapshot.verify()
    if not isinstance(updates, dict) or set(updates) - DEFAULTS["security"].keys():
        raise SettingsError("this editor changes only security preference lists")
    candidate = copy.deepcopy(snapshot.document)
    if updates:
        candidate.setdefault("defaults", {}).setdefault("security", {}).update(copy.deepcopy(updates))
    candidate = validate_document(candidate)

    def verify_sources():
        snapshot.verify()
        if check_sources is not None:
            check_sources()

    owned = snapshot.owned_policy()
    if candidate == snapshot.document or all(updates[name] == owned[name] for name in updates):
        verify_sources()
        snapshot.verify()
        return snapshot.expected_revision
    return write_settings(candidate, home=snapshot.home, expected_revision=snapshot.expected_revision,
                          check_sources=verify_sources)
