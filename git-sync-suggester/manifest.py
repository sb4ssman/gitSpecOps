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

**v3 closes the last two leaks and shrinks the record.** `branch` was a human-authored
string — `feature/acquire-northwind` says more than a repository name does — so it becomes
`branch_id`, an HMAC under the same fleet secret, with readable names kept in the local-only
catalog exactly as repository names already are. `upstream` was a string but every consumer
only ever tested it for truthiness, so it becomes the boolean `has_upstream`: strictly less
information published, and nothing lost. Identifiers also shrink — 128 bits of HMAC for a
repository and 64 for a branch are far beyond collision range here — which matters at scale,
where the record size is what decides how many repositories fit in one manifest.

See `.agents/knowledge/manifest-privacy.md` for the full analysis.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

SCHEMA_VERSION = 3
FLEET_SECRET_BYTES = 32
FLEET_ID_LABEL = b"gitspecops-sync-suggester-fleet-id"
BRANCH_LABEL = b"branch:"
# 128 bits for a repository and 64 for a branch. Both are far beyond collision range for any
# realistic fleet, and the saving is what keeps a large manifest inside one API read.
REPO_ID_HEX = 32
BRANCH_ID_HEX = 16

MANIFEST_KEYS = frozenset({
    "schema_version", "fleet_id", "machine_id", "machine_label", "observed_at", "repositories",
})
REPOSITORY_KEYS = frozenset({
    "repo_id", "branch_id", "has_upstream", "upstream_observed_at", "ahead", "behind",
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


def _digest(data: bytes, secret: str | None, length: int) -> str:
    """HMAC under the fleet secret, or a plain hash when previewing without a fleet."""
    if secret is None:
        return hashlib.sha256(data).hexdigest()[:length]
    if not is_fleet_secret(secret):
        raise ValueError("fleet secret must be 64 hexadecimal characters")
    return hmac.new(bytes.fromhex(secret), data, hashlib.sha256).hexdigest()[:length]


def repository_id(host: str, owner: str, name: str, secret: str | None = None) -> str:
    """Digest of a canonical, case-insensitive remote identity.

    With a fleet secret this is an HMAC and is meaningless to anyone without that secret.
    Without one it falls back to a plain hash, which is only ever used for a local preview
    that is never published — `build_manifest` requires a fleet id, so an unsalted identity
    cannot reach the transport.
    """
    identity = f"{host.lower()}/{owner.lower()}/{name.lower()}".encode("utf-8")
    return _digest(identity, secret, REPO_ID_HEX)


def branch_id(branch: str | None, secret: str | None = None) -> str | None:
    """Digest of a branch name, or None on a detached HEAD.

    Branch names are case-sensitive in git, so unlike repository identities this is not
    lowercased — `Feature/X` and `feature/x` are genuinely different branches.
    """
    if not branch:
        return None
    return _digest(BRANCH_LABEL + branch.encode("utf-8"), secret, BRANCH_ID_HEX)


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
    """Validate the small v3 boundary and reject fields that could leak local metadata."""
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    extra_manifest_keys = set(value) - MANIFEST_KEYS
    if extra_manifest_keys:
        raise ValueError(f"manifest has forbidden/unknown fields: {sorted(extra_manifest_keys)}")
    version = value.get("schema_version")
    if version != SCHEMA_VERSION:
        detail = (" (written by an older Sync Suggester; re-run 'check' on that machine)"
                  if version in (1, 2) else "")
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
        _require_digest(repo.get("repo_id"), REPO_ID_HEX, f"repositories[{index}].repo_id")
        if repo.get("branch_id") is not None:
            _require_digest(repo["branch_id"], BRANCH_ID_HEX,
                            f"repositories[{index}].branch_id")
        if not isinstance(repo.get("has_upstream", False), bool):
            raise ValueError(f"repositories[{index}].has_upstream must be a boolean")
    return value


def _require_digest(value: object, length: int, label: str) -> None:
    if not isinstance(value, str) or len(value) != length:
        raise ValueError(f"{label} must be a {length}-character hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} is not hexadecimal") from exc


def encode_manifest(value: dict) -> bytes:
    validate_manifest(value)
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def decode_manifest(payload: bytes) -> dict:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest JSON: {exc}") from exc
    return validate_manifest(value)
