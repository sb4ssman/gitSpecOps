"""Local-folder manifest transport.

The user's cloud client, Syncthing, or ordinary filesystem owns replication. This module
only reads machine manifests and atomically replaces the current machine's file.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from manifest import decode_manifest, encode_manifest

SAFE_MACHINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def atomic_write_bytes(destination: Path, payload: bytes) -> Path:
    """Replace `destination` in one step, never leaving a half-written file behind.

    A cloud-sync client (or a peer reader) may look at this directory at any instant, so
    the file must only ever appear complete. The temp file is created in the destination's
    own directory so `os.replace` stays on one filesystem and stays atomic.
    """
    destination = Path(destination)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}-", suffix=".tmp",
                                     dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return destination


class FolderTransport:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.machines_dir = self.root / "machines"

    def list_manifests(self) -> list[str]:
        if not self.machines_dir.is_dir():
            return []
        return sorted(path.name for path in self.machines_dir.glob("*.json") if path.is_file())

    def read_manifest(self, name: str) -> dict:
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("manifest name must be a plain .json filename")
        return decode_manifest((self.machines_dir / name).read_bytes())

    def write_own_manifest(self, machine_id: str, manifest: dict) -> Path:
        if not SAFE_MACHINE_ID.fullmatch(machine_id):
            raise ValueError("machine_id may contain only letters, digits, dot, underscore, and dash")
        if manifest.get("machine_id") != machine_id:
            raise ValueError("manifest machine_id does not match the destination")
        payload = encode_manifest(manifest)
        self.machines_dir.mkdir(parents=True, exist_ok=True)
        return atomic_write_bytes(self.machines_dir / f"{machine_id}.json", payload)

    def doctor(self) -> dict:
        return {
            "root": str(self.root),
            "exists": self.root.is_dir(),
            "machines_exists": self.machines_dir.is_dir(),
            "manifest_count": len(self.list_manifests()),
        }
