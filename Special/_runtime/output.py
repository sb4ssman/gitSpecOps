"""Shared presentation redaction and exclusive optional reports. No output on import.

Reports use a unique filename, never overwrite and never fall back. Redaction uses protected
literals and existing offline credential checks, without live identity discovery. Logs never
receive raw results. Trusted callable users may retain raw results separately.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from Special._runtime.files import prepare_directory, RuntimeIOError
from Special.security._checks._secrets import check as credential_candidates
from Special.security._me import Policy


def fleet_key_record(secret, *, show=False):
    """Explicit local disclosure channel; default hides the key, independent of logging.

    show=True returns the raw key to the current caller/output. An agent capturing that output
    sees it too; this is intent, not an isolation boundary. Callers never send it to logs/state.
    """
    if not isinstance(secret, str) or re.fullmatch(r"[0-9a-fA-F]{64}", secret) is None or type(show) is not bool:
        raise ValueError("a valid configured fleet key and explicit display choice are required")
    return {"schema_version": 1, "configured": True, "disclosed": show,
            "fleet_key": secret if show else "(hidden)"}


def conceal(value, protected=()):
    """Return presentation data with protected literals and credential candidates removed."""
    if isinstance(value, str):
        private = {item for item in protected if item}
        private.update(hit.value for hit in credential_candidates(value, "presentation", Policy()))
        value = re.sub(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1[redacted]@", value)
        for item in sorted(private, key=len, reverse=True):
            value = re.sub(re.escape(item), "[redacted]", value, flags=re.IGNORECASE)
        return value
    if isinstance(value, dict):
        return {conceal(key, protected): conceal(item, protected) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [conceal(item, protected) for item in value]
    return value


class ReportSink:
    """Reserve a new report before effects, then complete or discard that one file."""

    def __init__(self, directory: Path, format: str, *, prefix: str = "archive-update"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", prefix):
            raise ValueError("invalid report prefix")
        directory = prepare_directory(directory)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.path = directory / f"{prefix}-{stamp}-{uuid4().hex[:8]}.{'json' if format == 'json' else 'txt'}"
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")

    def write(self, text: str) -> None:
        """Flush a complete result; on failure discard this invocation's incomplete file."""
        try:
            self.handle.write(text.rstrip() + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())
            self.handle.close()
        except OSError:
            self.abort()
            raise RuntimeIOError("report_write") from None

    def abort(self) -> None:
        """Best-effort cleanup; an incomplete file is never advertised as a valid report."""
        try:
            self.handle.close()
        except OSError:
            pass
        try:
            self.path.unlink()
        except OSError:
            pass
