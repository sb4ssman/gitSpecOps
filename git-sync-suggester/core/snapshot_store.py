"""Recovery snapshot store: where bundles live, how long, and who may touch them.

`capture.py` builds a bundle; this module puts it somewhere a second machine can reach and keeps
that place bounded. See `docs/RECOVERY-DESIGN.md` ("Delivery and retention") for the contract.

Layout, beneath a capture location the user confirmed separately from the status folder:

    gitspecops-snapshots/v1/<machine_id>/bundles/<repo_id>/<version>.json.gz
    gitspecops-snapshots/v1/<machine_id>/acks/<source_machine>/<repo_id>/<version>.json

**Each machine writes only beneath its own `<machine_id>` directory.** A source writes and retires
its own bundles; a receiver records that it verified someone else's bundle under *its own* `acks`
directory. No file is ever written by two machines, so a sync client never has to resolve a
conflict between them, and one machine can never delete another's recovery copy.

**A folder write is not durability.** A bundle placed in the synced folder has only reached this
disk. It becomes "recoverable elsewhere" when another machine has read it back, verified its
checksum, and written an acknowledgement naming that checksum. The store reports those states
separately and never promotes one into the next.

**Bounded storage never costs the last copy.** Superseded versions are pruned by count, and
anything past the retention period expires as explicit policy. Making room for a new capture
never deletes the newest version of any repository: at quota, the new capture is refused.

**Everything read from the folder is untrusted.** Another machine wrote it. Identifiers are
validated before they become paths, decompression is bounded, and a bundle is only returned
after its format and checksum verify.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
from pathlib import Path
import re
import secrets

from capture import FORMAT, FORMAT_VERSION, checksum_of
from Basic._files import atomic_write_bytes
from folder_transport import SAFE_MACHINE_ID

STORE_DIR = "gitspecops-snapshots"
LAYOUT_VERSION = "v1"
BUNDLE_SUFFIX = ".json.gz"

MAX_VERSIONS_PER_REPO = 10
MAX_STORE_BYTES = 250 * 1024 * 1024
RETENTION = timedelta(days=7)
# Capture refuses content above 10 MiB; JSON and base64 inflate that, so reads allow headroom
# while still bounding what a hostile or corrupt file can make this machine allocate.
MAX_DECODED_BYTES = 32 * 1024 * 1024
MAX_ACK_BYTES = 4096

REPO_ID = re.compile(r"^[0-9a-f]{32}$")
# Sortable UTC timestamp plus randomness: ordering without reading bundle bodies, and no two
# captures in the same second can collide.
VERSION = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{16}$")
CHECKSUM = re.compile(r"^[0-9a-f]{64}$")


class StoreRefused(Exception):
    """A deliberate refusal the user should see: quota, location, or an unverifiable bundle."""


def _require(pattern: re.Pattern, value, what: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise StoreRefused(f"invalid {what}")
    return value


def _within(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
    except ValueError:
        return False
    return True


def validate_location(location, *, status_folder=None, roots=()) -> list[str]:
    """Check a proposed capture location. Refuses what is unsafe; returns what needs a warning.

    Refused outright:
      * a location inside an observed root. Writing a snapshot raises filesystem events, which
        would look like new work, which would trigger another capture -- an endless loop, and
        one that writes recovery copies into the very libraries being observed.

    Warned, because only the user can judge them:
      * the same place as the status folder, or inside it. That folder may have been chosen
        while it held only names-free manifests; bundles hold filenames and source.
      * sharing. Whether a sync folder is shared with other people cannot be detected from the
        filesystem, so the warning always asks rather than silently assuming it is private.
    """
    location = Path(location).expanduser()
    if not location.is_dir():
        raise StoreRefused("the capture location must be an existing folder")
    resolved = location.resolve()
    for root in roots:
        root = Path(root).expanduser().resolve()
        if _within(resolved, root) or _within(root, resolved):
            raise StoreRefused("the capture location overlaps an observed repository root; "
                               "snapshots written there would trigger capture again")
    warnings = []
    if status_folder:
        status = Path(status_folder).expanduser().resolve()
        if _within(resolved, status) or _within(status, resolved):
            warnings.append("This is the same place your status manifests are published. Status "
                            "is names-free; snapshots contain filenames and source code.")
    warnings.append("Confirm this folder is yours alone. Anyone the folder is shared with can "
                    "read captured source, and gitSpecOps cannot detect sharing.")
    return warnings


@dataclass(frozen=True)
class Version:
    machine_id: str
    repo_id: str
    version: str
    size: int
    created_at: datetime

    @property
    def expires_at(self) -> datetime:
        return self.created_at + RETENTION


def new_version_id(now: datetime) -> str:
    return f"{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}"


def _version_time(version: str) -> datetime:
    return datetime.strptime(version[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def content_digest(body: dict) -> str:
    """What changed, independent of when it was captured. Used to skip identical recaptures."""
    return checksum_of({key: value for key, value in body.items()
                        if key not in ("captured_at", "checksum")})


def _bounded_json(payload: bytes, limit: int, compressed: bool) -> dict:
    try:
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise StoreRefused("snapshot exceeds the size a bundle may decode to")
        value = json.loads(payload.decode("utf-8"))
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreRefused("snapshot is corrupt or truncated") from exc
    if not isinstance(value, dict):
        raise StoreRefused("snapshot is not a bundle object")
    return value


def verify_bundle(body: dict) -> dict:
    """Format and integrity, before anything else trusts a single field."""
    if body.get("format") != FORMAT:
        raise StoreRefused("not a gitSpecOps recovery bundle")
    if body.get("format_version") != FORMAT_VERSION:
        raise StoreRefused("recovery bundle format version is not supported by this version")
    if not isinstance(body.get("checksum"), str) or checksum_of(body) != body["checksum"]:
        raise StoreRefused("snapshot checksum does not match its content")
    _require(REPO_ID, body.get("repo_id"), "repository id in bundle")
    _require(SAFE_MACHINE_ID, body.get("machine_id"), "machine id in bundle")
    return body


class SnapshotStore:
    """One machine's view of the shared store. Writes are confined to `machine_id`'s subtree."""

    def __init__(self, location, machine_id: str, *, clock=None):
        self.machine_id = _require(SAFE_MACHINE_ID, machine_id, "machine id")
        self.base = Path(location).expanduser().resolve() / STORE_DIR / LAYOUT_VERSION
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- paths -------------------------------------------------------------------------------

    def _machine_dir(self, machine_id: str) -> Path:
        path = (self.base / _require(SAFE_MACHINE_ID, machine_id, "machine id")).resolve()
        if not _within(path, self.base):
            raise StoreRefused("path escapes the snapshot store")
        return path

    def _bundle_path(self, machine_id: str, repo_id: str, version: str) -> Path:
        _require(REPO_ID, repo_id, "repository id")
        _require(VERSION, version, "snapshot version")
        return self._machine_dir(machine_id) / "bundles" / repo_id / f"{version}{BUNDLE_SUFFIX}"

    def _ack_path(self, receiver: str, source: str, repo_id: str, version: str) -> Path:
        _require(REPO_ID, repo_id, "repository id")
        _require(VERSION, version, "snapshot version")
        _require(SAFE_MACHINE_ID, source, "source machine id")
        return self._machine_dir(receiver) / "acks" / source / repo_id / f"{version}.json"

    # ---- listing -----------------------------------------------------------------------------

    def machines(self) -> list[str]:
        if not self.base.is_dir():
            return []
        return sorted(path.name for path in self.base.iterdir()
                      if path.is_dir() and SAFE_MACHINE_ID.fullmatch(path.name))

    def versions(self, machine_id: str | None = None, repo_id: str | None = None) -> list[Version]:
        """Oldest first. Entries that are not well-formed are ignored, never interpreted."""
        machine_id = machine_id or self.machine_id
        bundles = self._machine_dir(machine_id) / "bundles"
        if not bundles.is_dir():
            return []
        found = []
        for repo_dir in sorted(bundles.iterdir()):
            if not repo_dir.is_dir() or not REPO_ID.fullmatch(repo_dir.name):
                continue
            if repo_id is not None and repo_dir.name != repo_id:
                continue
            for item in repo_dir.iterdir():
                name = item.name.removesuffix(BUNDLE_SUFFIX)
                if (not item.name.endswith(BUNDLE_SUFFIX) or not VERSION.fullmatch(name)
                        or item.is_symlink() or not item.is_file()):
                    continue
                found.append(Version(machine_id, repo_dir.name, name, item.stat().st_size,
                                     _version_time(name)))
        return sorted(found, key=lambda v: (v.repo_id, v.version))

    def used_bytes(self) -> int:
        return sum(version.size for version in self.versions())

    # ---- reading -----------------------------------------------------------------------------

    def read(self, machine_id: str, repo_id: str, version: str) -> dict:
        path = self._bundle_path(machine_id, repo_id, version)
        if path.is_symlink() or not path.is_file():
            raise StoreRefused("that snapshot is not in the store")
        if path.stat().st_size > MAX_DECODED_BYTES:
            raise StoreRefused("snapshot file exceeds the size a bundle may occupy")
        body = verify_bundle(_bounded_json(path.read_bytes(), MAX_DECODED_BYTES, True))
        # The path is part of the claim. A bundle copied into another machine's or repository's
        # directory must not be believed as belonging there.
        if body["machine_id"] != machine_id or body["repo_id"] != repo_id:
            raise StoreRefused("snapshot does not belong where it was found")
        return body

    # ---- writing (own subtree only) ----------------------------------------------------------

    def write(self, body: dict) -> dict:
        """Store one bundle. Returns `{"written": bool, "version", "pruned": [...], "reason"}`."""
        verify_bundle(body)
        if body["machine_id"] != self.machine_id:
            raise StoreRefused("a machine may only store its own snapshots")
        repo_id = body["repo_id"]
        existing = self.versions(repo_id=repo_id)
        if existing:
            latest = self.read(self.machine_id, repo_id, existing[-1].version)
            if content_digest(latest) == content_digest(body):
                return {"written": False, "version": existing[-1].version, "pruned": [],
                        "reason": "unchanged since the last snapshot"}

        raw = (json.dumps(body, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        if len(raw) > MAX_DECODED_BYTES:
            raise StoreRefused("snapshot exceeds the size a bundle may decode to")
        payload = gzip.compress(raw, compresslevel=6, mtime=0)

        now = self.clock()
        pruned = self._prune_superseded(repo_id, keep=MAX_VERSIONS_PER_REPO - 1)
        pruned += self.expire(now, spare_latest_of={repo_id})
        if self.used_bytes() + len(payload) > MAX_STORE_BYTES:
            pruned += self._make_room(len(payload))
        if self.used_bytes() + len(payload) > MAX_STORE_BYTES:
            raise StoreRefused("the snapshot store is full; only the newest snapshot of each "
                               "repository remains, so this capture is refused rather than "
                               "deleting one of them")

        version = new_version_id(now)
        path = self._bundle_path(self.machine_id, repo_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, payload)
        return {"written": True, "version": version, "pruned": pruned, "reason": ""}

    def _remove(self, version: Version) -> Version:
        path = self._bundle_path(self.machine_id, version.repo_id, version.version)
        if version.machine_id != self.machine_id or not _within(path, self._machine_dir(
                self.machine_id)):
            raise StoreRefused("a machine may only remove its own snapshots")
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()  # only succeeds once the repository has no versions left
        except OSError:
            pass
        return version

    def _prune_superseded(self, repo_id: str, keep: int) -> list[Version]:
        versions = self.versions(repo_id=repo_id)
        excess = versions[:max(0, len(versions) - keep)]
        return [self._remove(version) for version in excess]

    def _make_room(self, needed: int) -> list[Version]:
        """Oldest superseded versions first. The newest version of every repository is spared."""
        newest = {}
        for version in self.versions():
            newest[version.repo_id] = version.version
        candidates = sorted((v for v in self.versions() if newest[v.repo_id] != v.version),
                            key=lambda v: v.version)
        removed = []
        for version in candidates:
            if self.used_bytes() + needed <= MAX_STORE_BYTES:
                break
            removed.append(self._remove(version))
        return removed

    def expire(self, now: datetime | None = None, spare_latest_of=()) -> list[Version]:
        """Remove versions past retention: explicit policy, never evidence a commit happened.

        `spare_latest_of` protects a repository's newest version during a write for that same
        repository, which is about to be superseded by fresher content anyway.
        """
        now = now or self.clock()
        newest = {}
        for version in self.versions():
            newest[version.repo_id] = version.version
        removed = []
        for version in self.versions():
            if version.expires_at > now:
                continue
            if version.repo_id in spare_latest_of and newest[version.repo_id] == version.version:
                continue
            removed.append(self._remove(version))
        return removed

    def expiring(self, within: timedelta, now: datetime | None = None) -> list[Version]:
        """Newest versions -- the last recoverable copy -- that will expire soon. For warnings."""
        now = now or self.clock()
        newest = {}
        for version in self.versions():
            newest[version.repo_id] = version
        return [v for v in newest.values() if now < v.expires_at <= now + within]

    # ---- deletion the user asked for ---------------------------------------------------------

    def plan_deletion(self, repo_id: str | None = None) -> dict:
        """Preview what a user-requested deletion would remove: count, size, and scope."""
        if repo_id is not None:
            _require(REPO_ID, repo_id, "repository id")
        targets = self.versions(repo_id=repo_id)
        return {"machine_id": self.machine_id, "repo_id": repo_id,
                "scope": "one repository" if repo_id else "every snapshot from this machine",
                "count": len(targets), "bytes": sum(v.size for v in targets),
                "versions": [(v.repo_id, v.version) for v in targets],
                "note": "Removing files from a synced folder cannot erase copies your sync "
                        "provider or another device has already kept."}

    def delete(self, plan: dict) -> list[Version]:
        """Execute a previewed plan exactly: nothing it did not list is removed."""
        if plan.get("machine_id") != self.machine_id:
            raise StoreRefused("a deletion plan may only remove this machine's snapshots")
        listed = {tuple(item) for item in plan.get("versions", [])}
        return [self._remove(v) for v in self.versions() if (v.repo_id, v.version) in listed]

    def retire(self, repo_id: str, version: str) -> None:
        """Remove one version after the caller proved its content reached a real commit."""
        self._remove(Version(self.machine_id, repo_id, version, 0, _version_time(
            _require(VERSION, version, "snapshot version"))))

    # ---- acknowledgement: another machine verified it can read the bundle -------------------

    def acknowledge(self, source: str, repo_id: str, version: str) -> dict:
        """Read a peer's bundle back, verify it, and record that under this machine's own tree."""
        if source == self.machine_id:
            raise StoreRefused("a machine cannot acknowledge its own snapshot; that proves nothing "
                               "about another device")
        body = self.read(source, repo_id, version)
        record = {"format": "gitspecops.recovery.ack", "source_machine": source,
                  "repo_id": repo_id, "version": version, "bundle_checksum": body["checksum"],
                  "acknowledged_by": self.machine_id,
                  "acknowledged_at": self.clock().isoformat()}
        path = self._ack_path(self.machine_id, source, repo_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, (json.dumps(record, sort_keys=True) + "\n").encode())
        return record

    def acknowledgements(self, repo_id: str, version: str) -> list[str]:
        """Machines that verified *this exact* bundle. A stale or mismatched ack does not count."""
        path = self._bundle_path(self.machine_id, repo_id, version)
        if not path.is_file():
            return []
        try:
            checksum = self.read(self.machine_id, repo_id, version)["checksum"]
        except StoreRefused:
            return []
        confirmed = []
        for receiver in self.machines():
            if receiver == self.machine_id:
                continue
            ack = self._ack_path(receiver, self.machine_id, repo_id, version)
            if ack.is_symlink() or not ack.is_file() or ack.stat().st_size > MAX_ACK_BYTES:
                continue
            try:
                record = _bounded_json(ack.read_bytes(), MAX_ACK_BYTES, False)
            except StoreRefused:
                continue
            if (record.get("bundle_checksum") == checksum
                    and record.get("acknowledged_by") == receiver
                    and record.get("source_machine") == self.machine_id
                    and CHECKSUM.fullmatch(str(record.get("bundle_checksum")))):
                confirmed.append(receiver)
        return confirmed

    def status(self, repo_id: str, version: str) -> str:
        """`missing`, `written`, or `recoverable elsewhere`. A folder write is only `written`."""
        if not self._bundle_path(self.machine_id, repo_id, version).is_file():
            return "missing"
        return "recoverable elsewhere" if self.acknowledgements(repo_id, version) else "written"
