"""One fleet peer, or one local operation that acts on the observed checkouts, per configuration.

Why:          a catch-up or materialize running beside a peer (which may itself act under a
              standing consent) would race it on the same checkouts.
Reads:        nothing; holds an OS lock on `fleet-app.lock` in the fleet directory.
May change:   creates that lock file. The OS releases the lock after a crash too.
Results:      a context manager; ValueError when another peer or operation holds the lock.
Layer:        Special: this machine, once.
Status:       working
"""
from __future__ import annotations

import sys
from contextlib import contextmanager


PEER_LOCK = "fleet-app.lock"
TRAY_LOCK = "tray.lock"  # one tray per profile, held for the tray's whole life (2026-11-15)


@contextmanager
def app_lock(directory, name: str = PEER_LOCK):
    """One peer (or one tray) per local configuration; the OS releases the lock after a crash too."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open("a+b") as handle:
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("this fleet app is already running for this configuration") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
