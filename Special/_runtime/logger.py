"""One explicit stdlib logging seam; no handler or settings lookup on import.

Configure from resolved preferences. Cooperating CLI/app writers lock each append/rotation
and close the file before releasing it. Busy/stale locks and write failures are errors;
no stale-lock deletion or fallback. Only event names and numeric counters are accepted.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from Special._runtime.files import checked_path, prepare_directory, RuntimeIOError

LOCK_WAIT_SECONDS = 1.0
COUNTERS = {"roots", "repositories", "updated", "failed", "skipped", "exit_code", "attempted", "excluded"}


class _LockedHandler(RotatingFileHandler):
    @contextmanager
    def file_lock(self):
        path = Path(self.baseFilename + ".lock")
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            checked_path(path)
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeIOError("logging_busy") from None
                time.sleep(0.02)
        os.close(descriptor)
        try:
            for index in range(self.backupCount + 1):
                checked_path(Path(self.baseFilename + (f".{index}" if index else "")))
            yield
        finally:
            path.unlink()

    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        return os.fdopen(descriptor, "a", encoding="utf-8", newline="\n")

    def probe(self):
        with self.file_lock(), self._open():
            pass

    def emit(self, record):
        try:
            with self.file_lock():
                try:
                    super().emit(record)
                finally:
                    if self.stream is not None:
                        self.stream.close()
                        self.stream = None
        except RuntimeIOError:
            raise
        except OSError:
            raise RuntimeIOError("logging_write") from None

    def handleError(self, record):
        raise RuntimeIOError("logging_write") from None

    def doRollover(self):
        if self.backupCount:
            return super().doRollover()
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        descriptor = os.open(self.baseFilename, os.O_WRONLY | os.O_TRUNC)
        os.close(descriptor)


class OperationalLog:
    """An invocation-owned logger accepting no free-form paths or diagnostic values."""

    def __init__(self, logger=None, handler=None, component=None, run_id=None):
        self.logger, self.handler = logger, handler
        self.component, self.run_id = component, run_id

    def event(self, event: str, **counters: int) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", event) or set(counters) - COUNTERS or any(
                type(value) is not int or value < 0 for value in counters.values()):
            raise ValueError("operational logs accept event names and nonnegative counters only")
        if self.logger is not None:
            level = logging.ERROR if counters.get("failed", 0) or counters.get("exit_code", 0) else logging.INFO
            self.logger.log(level, json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                         "component": self.component, "run_id": self.run_id,
                                         "event": event, **counters}, sort_keys=True))

    def close(self) -> None:
        if self.handler is not None:
            self.logger.removeHandler(self.handler)
            self.handler.close()


def configure_logging(settings, component: str) -> OperationalLog:
    """Prepare required logging before effects; disabled logging performs no I/O."""
    preferences = settings.values["logging"]
    if not preferences["enabled"]:
        return OperationalLog()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", component):
        raise ValueError("invalid logging component")
    try:
        directory = prepare_directory(preferences["directory"])
        handler = _LockedHandler(directory / f"{component}.log", maxBytes=preferences["max_bytes"],
                                 backupCount=preferences["backup_count"], delay=True, encoding="utf-8")
        handler.probe()
    except RuntimeIOError:
        raise
    except OSError:
        raise RuntimeIOError("logging_setup") from None
    run_id = uuid4().hex
    logger = logging.Logger(f"gitspecops.{component}.{run_id}", level=preferences["level"])
    logger.propagate = False
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return OperationalLog(logger, handler, component, run_id)
