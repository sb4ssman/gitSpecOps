"""Privacy-minimized Sync Suggester manifest primitives.

Synced manifests contain repository identity digests and status facts only. Display names,
remote URLs, local paths, filenames, diffs, and source content belong in local-only state.

**Why v2 salts the identity.** v1 hashed `host/owner/name` with a bare SHA-256. That input
space is tiny — anyone holding the state folder could hash candidate strings (a wordlist of
repository names against an account they already suspect) until the digests matched. Hashing
a low-entropy identifier is obfuscation, not anonymity. v2 uses HMAC-SHA256 under a fleet
secret that lives only in each machine's local config and is carried between machines by the
user, never through the transport — a state folder alone no longer reveals which
repositories a machine holds.

v2 also drops `head`. A commit SHA identifies a public repository outright, and nothing in
this tool ever read it: classification works from ahead/behind, the dirty counts, `stashes`,
and `operation`. It was the single strongest de-anonymizer in the record and it was dead
weight.

See `.agents/knowledge/manifest-privacy.md` for the full analysis.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

SCHEMA_VERSION = 2
FLEET_SECRET_BYTES = 32
FLEET_ID_LABEL = b"gitspecops-sync-suggester-fleet-id"

MANIFEST_KEYS = frozenset({
    "schema_version", "fleet_id", "machine_id", "machine_label", "observed_at", "repositories",
})
REPOSITORY_KEYS = frozenset({
    "repo_id", "branch", "upstream", "upstream_observed_at", "ahead", "behind",
    "staged", "unstaged", "untracked", "stashes", "operation",
})


def utc_now() -> str:
    """Current UTC time in the manifest's stable ISO-8601 form."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_fleet_secret() -> str:
    """A fresh fleet secret. Lives in local config only; never written to the transport."""
    return secrets.token_hex(FLEET_SECRET_BYTES)


def is_fleet_secret(value: object) -> bool:
    if not isinstance(value, str) or len(value) != FLEET_SECRET_BYTES * 2:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def fleet_id_for(secret: str) -> str:
    """A public, non-secret label for a fleet, so a mismatched secret is detectable.

    Without this, joining with the wrong secret produces a manifest whose every `repo_id`
    differs from the others — the machines would silently appear to share no repositories at
    all, which looks like a data problem rather than a configuration one.
    """
    if not is_fleet_secret(secret):
        raise ValueError("fleet secret must be 64 hexadecimal characters")
    return hmac.new(bytes.fromhex(secret), FLEET_ID_LABEL, hashlib.sha256).hexdigest()[:16]


def repository_id(host: str, owner: str, name: str, secret: str | None = None) -> str:
    """Digest of a canonical, case-insensitive remote identity.

    With a fleet secret this is an HMAC and is meaningless to anyone without that secret.
    Without one it falls back to a plain hash, which is only ever used for a local preview
    that is never published — `build_manifest` requires a fleet id, so an unsalted identity
    cannot reach the transport.
    """
    identity = f"{host.lower()}/{owner.lower()}/{name.lower()}".encode("utf-8")
    if secret is None:
        return hashlib.sha256(identity).hexdigest()
    if not is_fleet_secret(secret):
        raise ValueError("fleet secret must be 64 hexadecimal characters")
    return hmac.new(bytes.fromhex(secret), identity, hashlib.sha256).hexdigest()


def build_manifest(fleet_id: str, machine_id: str, machine_label: str, repositories: list[dict],
                   observed_at: str | None = None) -> dict:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "fleet_id": fleet_id,
        "machine_id": machine_id,
        "machine_label": machine_label,
        "observed_at": observed_at or utc_now(),
        "repositories": repositories,
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(value: object) -> dict:
    """Validate the small v2 boundary and reject fields that could leak local metadata."""
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    extra_manifest_keys = set(value) - MANIFEST_KEYS
    if extra_manifest_keys:
        raise ValueError(f"manifest has forbidden/unknown fields: {sorted(extra_manifest_keys)}")
    version = value.get("schema_version")
    if version != SCHEMA_VERSION:
        detail = (" (written by an older Sync Suggester; re-run 'check' on that machine)"
                  if version == 1 else "")
        raise ValueError(f"unsupported schema_version: {version!r}{detail}")
    for key in ("fleet_id", "machine_id", "machine_label", "observed_at"):
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
            raise ValueError(f"repositories[{index}].repo_id must be a 64-character hex digest")
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
