"""Privacy-minimized Sync Suggester manifest primitives.

Synced manifests contain repository identity hashes and status facts only. Display names,
remote URLs, local paths, filenames, diffs, and source content belong in local-only state.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

SCHEMA_VERSION = 1
MANIFEST_KEYS = frozenset({
    "schema_version", "machine_id", "machine_label", "observed_at", "repositories",
})
REPOSITORY_KEYS = frozenset({
    "repo_id", "branch", "head", "upstream", "upstream_observed_at", "ahead", "behind",
    "staged", "unstaged", "untracked", "stashes", "operation",
})


def utc_now() -> str:
    """Current UTC time in the manifest's stable ISO-8601 form."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repository_id(host: str, owner: str, name: str) -> str:
    """Hash a canonical, case-insensitive remote identity."""
    identity = f"{host.lower()}/{owner.lower()}/{name.lower()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_manifest(machine_id: str, machine_label: str, repositories: list[dict],
                   observed_at: str | None = None) -> dict:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "machine_id": machine_id,
        "machine_label": machine_label,
        "observed_at": observed_at or utc_now(),
        "repositories": repositories,
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(value: object) -> dict:
    """Validate the small v1 boundary and reject fields that could leak local metadata."""
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    extra_manifest_keys = set(value) - MANIFEST_KEYS
    if extra_manifest_keys:
        raise ValueError(f"manifest has forbidden/unknown fields: {sorted(extra_manifest_keys)}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {value.get('schema_version')!r}")
    for key in ("machine_id", "machine_label", "observed_at"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f"{key} must be a non-empty string")
    repositories = value.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("repositories must be a list")
    for index, repo in enumerate(repositories):
        if not isinstance(repo, dict):
            raise ValueError(f"repositories[{index}] must be an object")
        extra = set(repo) - REPOSITORY_KEYS
        if extra:
            raise ValueError(f"repositories[{index}] has forbidden/unknown fields: {sorted(extra)}")
        repo_id = repo.get("repo_id")
        if not isinstance(repo_id, str) or len(repo_id) != 64:
            raise ValueError(f"repositories[{index}].repo_id must be a SHA-256 hex digest")
        try:
            int(repo_id, 16)
        except ValueError as exc:
            raise ValueError(f"repositories[{index}].repo_id is not hexadecimal") from exc
    return value


def encode_manifest(value: dict) -> bytes:
    validate_manifest(value)
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def decode_manifest(payload: bytes) -> dict:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest JSON: {exc}") from exc
    return validate_manifest(value)
