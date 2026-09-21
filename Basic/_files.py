"""Write a file so that any reader, at any instant, sees either the old version or the new one.

A cloud-sync client, a peer, or a crashed run may look at a state file mid-write. Every JSON
this project persists -- manifests, configuration, registries, snapshot records -- is written
through `atomic_write_bytes` so a half-written file can never be what someone reads.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(destination: Path, payload: bytes) -> Path:
    """Replace `destination` in one step, never leaving a half-written file behind.

    The temp file is created in the destination's own directory so `os.replace` stays on one
    filesystem and stays atomic.
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
